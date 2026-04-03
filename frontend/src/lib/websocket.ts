export type ConnectionState = "connecting" | "connected" | "disconnected";

export interface StreamStartEvent {
	type: "stream_start";
	channel: string;
	message_id?: string;
}

export interface StreamDeltaEvent {
	type: "stream_delta";
	channel: string;
	content: string;
}

export interface StreamEndEvent {
	type: "stream_end";
	channel: string;
	message_id?: string;
	content?: string;
}

export interface ToolActivityEvent {
	type: "tool_activity";
	channel: string;
	content: string;
}

export interface SystemStatusEvent {
	type: "system_status";
	channel: string;
	content: string;
}

export interface ErrorEvent {
	type: "error";
	channel: string;
	content: string;
}

export type ServerEvent =
	| StreamStartEvent
	| StreamDeltaEvent
	| StreamEndEvent
	| ToolActivityEvent
	| SystemStatusEvent
	| ErrorEvent;

export interface ChatWebSocketCallbacks {
	onStreamStart?: (event: StreamStartEvent) => void;
	onStreamDelta?: (event: StreamDeltaEvent) => void;
	onStreamEnd?: (event: StreamEndEvent) => void;
	onToolActivity?: (event: ToolActivityEvent) => void;
	onSystemStatus?: (event: SystemStatusEvent) => void;
	onError?: (event: ErrorEvent) => void;
	onConnectionChange?: (state: ConnectionState) => void;
}

export class ChatWebSocket {
	private ws: WebSocket | null = null;
	private callbacks: ChatWebSocketCallbacks = {};
	private subscribedChannels = new Set<string>();
	private reconnectAttempts = 0;
	private maxReconnectDelay = 30000;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private intentionallyClosed = false;

	connectionState = $state<ConnectionState>("disconnected");

	constructor(callbacks: ChatWebSocketCallbacks = {}) {
		this.callbacks = callbacks;
	}

	connect() {
		if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
			return;
		}

		this.intentionallyClosed = false;
		this.setConnectionState("connecting");

		const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
		const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

		this.ws = new WebSocket(wsUrl);

		this.ws.onopen = () => {
			this.reconnectAttempts = 0;
			this.setConnectionState("connected");

			// Resubscribe to all channels
			for (const channel of this.subscribedChannels) {
				this.sendRaw({ type: "subscribe", channel });
			}
		};

		this.ws.onmessage = (event) => {
			try {
				const data = JSON.parse(event.data) as ServerEvent;
				this.handleEvent(data);
			} catch {
				// Ignore malformed messages
			}
		};

		this.ws.onclose = () => {
			this.ws = null;
			this.setConnectionState("disconnected");

			if (!this.intentionallyClosed) {
				this.scheduleReconnect();
			}
		};

		this.ws.onerror = () => {
			// onclose will fire after this
		};
	}

	disconnect() {
		this.intentionallyClosed = true;
		if (this.reconnectTimer) {
			clearTimeout(this.reconnectTimer);
			this.reconnectTimer = null;
		}
		if (this.ws) {
			this.ws.close();
			this.ws = null;
		}
		this.setConnectionState("disconnected");
	}

	subscribe(channel: string) {
		this.subscribedChannels.add(channel);
		if (this.ws?.readyState === WebSocket.OPEN) {
			this.sendRaw({ type: "subscribe", channel });
		}
	}

	sendMessage(channel: string, content: string) {
		this.sendRaw({ type: "message", channel, content });
	}

	abort(channel: string) {
		this.sendRaw({ type: "abort", channel });
	}

	private sendRaw(data: Record<string, unknown>) {
		if (this.ws?.readyState === WebSocket.OPEN) {
			this.ws.send(JSON.stringify(data));
		}
	}

	private handleEvent(event: ServerEvent) {
		switch (event.type) {
			case "stream_start":
				this.callbacks.onStreamStart?.(event);
				break;
			case "stream_delta":
				this.callbacks.onStreamDelta?.(event);
				break;
			case "stream_end":
				this.callbacks.onStreamEnd?.(event);
				break;
			case "tool_activity":
				this.callbacks.onToolActivity?.(event);
				break;
			case "system_status":
				this.callbacks.onSystemStatus?.(event);
				break;
			case "error":
				this.callbacks.onError?.(event);
				break;
		}
	}

	private setConnectionState(state: ConnectionState) {
		this.connectionState = state;
		this.callbacks.onConnectionChange?.(state);
	}

	private scheduleReconnect() {
		const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), this.maxReconnectDelay);
		this.reconnectAttempts++;

		this.reconnectTimer = setTimeout(() => {
			this.reconnectTimer = null;
			this.connect();
		}, delay);
	}
}
