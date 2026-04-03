import { ChatWebSocket, type ConnectionState, type FileAttachment } from "./websocket.js";
import { getMessages, type MessageRecord } from "./api.js";

export interface ChatMessage {
	id: string;
	dbId?: number;
	role: "user" | "assistant" | "system";
	content: string;
	timestamp: string;
	toolActivity?: string;
	files?: FileAttachment[];
}

interface ChannelState {
	messages: ChatMessage[];
	loadedOldest: boolean;
	loadingHistory: boolean;
}

let _activeAgent = $state<string | null>(null);
let _isStreaming = $state(false);
let _streamingContent = $state("");
let _streamingToolActivity = $state("");
let _connectionState = $state<ConnectionState>("disconnected");
let _channels = $state<Record<string, ChannelState>>({});

let ws: ChatWebSocket | null = null;
let messageCounter = 0;

function getChannel(agent: string): ChannelState {
	if (!_channels[agent]) {
		_channels[agent] = { messages: [], loadedOldest: false, loadingHistory: false };
	}
	return _channels[agent];
}

function generateTempId(): string {
	return `temp-${Date.now()}-${messageCounter++}`;
}

export const chat = {
	get activeAgent() {
		return _activeAgent;
	},
	get isStreaming() {
		return _isStreaming;
	},
	get streamingContent() {
		return _streamingContent;
	},
	get streamingToolActivity() {
		return _streamingToolActivity;
	},
	get connectionState() {
		return _connectionState;
	},
	get messages(): ChatMessage[] {
		if (!_activeAgent) return [];
		return getChannel(_activeAgent).messages;
	},

	init() {
		if (ws) return;

		ws = new ChatWebSocket({
			onStreamStart: (event) => {
				if (event.channel === _activeAgent) {
					_isStreaming = true;
					_streamingContent = "";
					_streamingToolActivity = "";
				}
			},
			onStreamDelta: (event) => {
				if (event.channel === _activeAgent) {
					_streamingContent += event.content;
				}
			},
			onStreamEnd: (event) => {
				if (event.channel === _activeAgent) {
					const channel = getChannel(event.channel);
					channel.messages = [
						...channel.messages,
						{
							id: event.message_id || generateTempId(),
							role: "assistant",
							content: event.content || _streamingContent,
							timestamp: new Date().toISOString(),
							files: event.files,
						},
					];
					_isStreaming = false;
					_streamingContent = "";
					_streamingToolActivity = "";
				}
			},
			onToolActivity: (event) => {
				if (event.channel === _activeAgent) {
					_streamingToolActivity = event.content;
				}
			},
			onSystemStatus: (event) => {
				if (event.channel === _activeAgent) {
					const channel = getChannel(event.channel);
					channel.messages = [
						...channel.messages,
						{
							id: generateTempId(),
							role: "system",
							content: event.content,
							timestamp: new Date().toISOString(),
						},
					];
				}
			},
			onError: (event) => {
				if (event.channel === _activeAgent) {
					_isStreaming = false;
					_streamingContent = "";
					_streamingToolActivity = "";
					const channel = getChannel(event.channel);
					channel.messages = [
						...channel.messages,
						{
							id: generateTempId(),
							role: "system",
							content: `Error: ${event.content}`,
							timestamp: new Date().toISOString(),
						},
					];
				}
			},
			onConnectionChange: (state) => {
				_connectionState = state;
			},
		});

		ws.connect();
	},

	destroy() {
		if (ws) {
			ws.disconnect();
			ws = null;
		}
	},

	async switchAgent(agentName: string) {
		_activeAgent = agentName;

		if (ws) {
			ws.subscribe(agentName);
		}

		const channel = getChannel(agentName);
		if (channel.messages.length === 0 && !channel.loadingHistory) {
			await this.loadHistory(agentName);
		}
	},

	async loadHistory(agentName: string) {
		const channel = getChannel(agentName);
		if (channel.loadingHistory || channel.loadedOldest) return;

		channel.loadingHistory = true;
		try {
			const oldestMsg = channel.messages.length > 0 ? channel.messages[0] : undefined;
			const beforeId = oldestMsg?.dbId;
			const records = await getMessages(agentName, beforeId, 50);

			if (records.length === 0) {
				channel.loadedOldest = true;
			} else {
				const newMessages: ChatMessage[] = records.map((r: MessageRecord) => ({
					id: String(r.id),
					dbId: r.id,
					role: r.role as "user" | "assistant" | "system",
					content: r.content,
					timestamp: r.created_at,
				}));

				// Prepend history (API returns chronological order)
				channel.messages = [...newMessages, ...channel.messages];
			}
		} catch {
			// Silently fail — user can retry
		} finally {
			channel.loadingHistory = false;
		}
	},

	sendMessage(content: string) {
		if (!_activeAgent || !ws) return;

		const channel = getChannel(_activeAgent);
		channel.messages = [
			...channel.messages,
			{
				id: generateTempId(),
				role: "user",
				content,
				timestamp: new Date().toISOString(),
			},
		];

		ws.sendMessage(_activeAgent, content);
	},

	abort() {
		if (!_activeAgent || !ws) return;
		ws.abort(_activeAgent);

		// If we were streaming, finalize partial content
		if (_isStreaming && _streamingContent) {
			const channel = getChannel(_activeAgent);
			channel.messages = [
				...channel.messages,
				{
					id: generateTempId(),
					role: "assistant",
					content: _streamingContent + "\n\n*(aborted)*",
					timestamp: new Date().toISOString(),
				},
			];
		}
		_isStreaming = false;
		_streamingContent = "";
		_streamingToolActivity = "";
	},
};
