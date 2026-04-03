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
