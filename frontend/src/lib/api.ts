export interface User {
	id: number;
	username: string;
	display_name: string;
	is_admin: boolean;
}

export interface Agent {
	name: string;
	status: string;
	provider?: string;
	model?: string;
	agent_type: string;
	linux_user: boolean;
	trust_level: string;
	can_contact: string[];
	accept_from: string[];
	manager?: string;
	workers: string[];
}

export interface AgentCreate {
	name: string;
	provider?: string;
	model?: string;
	agent_type?: string;
	linux_user?: boolean;
	linux_user_name?: string;
	permission_template?: string;
	trust_level?: string;
	can_contact?: string[];
	accept_from?: string[];
}

export interface AgentUpdate {
	provider?: string;
	model?: string;
	agent_type?: string;
	linux_user?: boolean;
	linux_user_name?: string;
	permission_template?: string;
	trust_level?: string;
	can_contact?: string[];
	accept_from?: string[];
	manager?: string;
	workers?: string[];
}

export interface AgentHierarchyNode {
	name: string;
	agent_type: string;
	status: string;
	workers: AgentHierarchyNode[];
}

export interface AgentHierarchyResponse {
	roots: AgentHierarchyNode[];
}

export interface PermissionTemplate {
	name: string;
	description: string;
	groups: string[];
	sudo_rules: string[];
}

export interface ApiError {
	detail: string;
}

const BASE_URL = import.meta.env.DEV ? "" : "";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
	const res = await fetch(`${BASE_URL}${path}`, {
		...options,
		credentials: "include",
		headers: {
			"Content-Type": "application/json",
			...options.headers,
		},
	});

	if (!res.ok) {
		const body = await res.json().catch(() => ({ detail: res.statusText }));
		throw new Error(body.detail || `Request failed: ${res.status}`);
	}

	if (res.status === 204) return undefined as T;
	return res.json();
}

export async function login(username: string, password: string): Promise<User> {
	return request<User>("/api/auth/login", {
		method: "POST",
		body: JSON.stringify({ username, password }),
	});
}

export async function setup(username: string, password: string): Promise<User> {
	return request<User>("/api/auth/setup", {
		method: "POST",
		body: JSON.stringify({ username, password }),
	});
}

export async function logout(): Promise<void> {
	return request<void>("/api/auth/logout", { method: "POST" });
}

export async function getMe(): Promise<User> {
	return request<User>("/api/auth/me");
}

export async function getAgents(): Promise<Agent[]> {
	return request<Agent[]>("/api/agents");
}

export async function getAgent(name: string): Promise<Agent> {
	return request<Agent>(`/api/agents/${name}`);
}

export async function createAgent(data: AgentCreate): Promise<Agent> {
	return request<Agent>("/api/agents", {
		method: "POST",
		body: JSON.stringify(data),
	});
}

export async function updateAgent(name: string, data: AgentUpdate): Promise<Agent> {
	return request<Agent>(`/api/agents/${name}`, {
		method: "PUT",
		body: JSON.stringify(data),
	});
}

export async function deleteAgent(name: string): Promise<void> {
	return request<void>(`/api/agents/${name}`, { method: "DELETE" });
}

export async function startAgent(name: string): Promise<{ status: string; agent: string }> {
	return request<{ status: string; agent: string }>(`/api/agents/${name}/start`, {
		method: "POST",
	});
}

export async function stopAgent(name: string): Promise<{ status: string; agent: string }> {
	return request<{ status: string; agent: string }>(`/api/agents/${name}/stop`, {
		method: "POST",
	});
}

export async function setAgentHierarchy(
	name: string,
	data: AgentUpdate,
): Promise<Agent> {
	return request<Agent>(`/api/agents/${name}/hierarchy`, {
		method: "PUT",
		body: JSON.stringify(data),
	});
}

export async function getAgentHierarchy(): Promise<AgentHierarchyResponse> {
	return request<AgentHierarchyResponse>("/api/agents/hierarchy/tree");
}

export async function getPermissionTemplates(): Promise<PermissionTemplate[]> {
	return request<PermissionTemplate[]>("/api/agents/templates/list");
}

export interface MessageRecord {
	id: number;
	role: string;
	content: string;
	created_at: string;
}

export async function getMessages(
	agentName: string,
	beforeId?: number,
	limit = 50,
): Promise<MessageRecord[]> {
	const params = new URLSearchParams({ limit: String(limit) });
	if (beforeId !== undefined) params.set("before_id", String(beforeId));
	return request<MessageRecord[]>(`/api/messages/${agentName}?${params}`);
}

// -- File API -----------------------------------------------------------------

export interface FileRecord {
	id: number;
	name: string;
	mime: string;
	size: number;
	url: string;
	thumbnail_url: string | null;
	created_at: string;
}

export async function uploadFile(file: File, agentName: string): Promise<FileRecord> {
	const formData = new FormData();
	formData.append("file", file);
	if (agentName) formData.append("agent_name", agentName);

	const res = await fetch("/api/files/upload", {
		method: "POST",
		credentials: "include",
		body: formData,
	});

	if (!res.ok) {
		const body = await res.json().catch(() => ({ detail: res.statusText }));
		throw new Error(body.detail || `Upload failed: ${res.status}`);
	}
	return res.json();
}

export function getFileUrl(fileId: number): string {
	return `/api/files/${fileId}`;
}

export function getThumbnailUrl(fileId: number): string {
	return `/api/files/${fileId}?thumbnail=true`;
}
