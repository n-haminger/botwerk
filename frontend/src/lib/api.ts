export interface User {
	id: number;
	username: string;
	display_name: string;
	is_admin: boolean;
}

export interface Agent {
	name: string;
	status: string;
	model?: string;
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
