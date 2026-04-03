<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";
	import {
		getUsers,
		createUser,
		updateUser,
		deleteUser,
		getAgents,
		getUserAgents,
		setUserAgents,
		type AdminUser,
		type Agent,
	} from "$lib/api.js";
	import { Button } from "$lib/components/ui/button/index.js";

	let users = $state<AdminUser[]>([]);
	let agents = $state<Agent[]>([]);
	let loading = $state(true);
	let error = $state("");

	// Create form
	let showCreate = $state(false);
	let newUsername = $state("");
	let newPassword = $state("");
	let newDisplayName = $state("");
	let newIsAdmin = $state(false);
	let createError = $state("");

	// Edit form
	let editingUser = $state<AdminUser | null>(null);
	let editPassword = $state("");
	let editDisplayName = $state("");
	let editIsAdmin = $state(false);
	let editError = $state("");

	// Agent assignment
	let assigningUser = $state<AdminUser | null>(null);
	let assignedAgents = $state<string[]>([]);
	let assignError = $state("");

	$effect(() => {
		if (!auth.loading && !auth.isAuthenticated) {
			goto(`${base}/login`);
		}
		if (!auth.loading && auth.user && !auth.user.is_admin) {
			goto(`${base}/chat`);
		}
	});

	$effect(() => {
		if (auth.isAuthenticated && auth.user?.is_admin) {
			refresh();
		}
	});

	async function refresh() {
		loading = true;
		error = "";
		try {
			const [u, a] = await Promise.all([getUsers(), getAgents()]);
			users = u;
			agents = a;
		} catch (e: any) {
			error = e.message || "Failed to load data";
		} finally {
			loading = false;
		}
	}

	async function handleCreate() {
		createError = "";
		try {
			await createUser({
				username: newUsername,
				password: newPassword,
				display_name: newDisplayName || undefined,
				is_admin: newIsAdmin,
			});
			showCreate = false;
			newUsername = "";
			newPassword = "";
			newDisplayName = "";
			newIsAdmin = false;
			await refresh();
		} catch (e: any) {
			createError = e.message || "Failed to create user";
		}
	}

	function startEdit(user: AdminUser) {
		editingUser = user;
		editDisplayName = user.display_name;
		editIsAdmin = user.is_admin;
		editPassword = "";
		editError = "";
	}

	async function handleEdit() {
		if (!editingUser) return;
		editError = "";
		try {
			const update: Record<string, unknown> = {};
			if (editDisplayName !== editingUser.display_name) update.display_name = editDisplayName;
			if (editIsAdmin !== editingUser.is_admin) update.is_admin = editIsAdmin;
			if (editPassword) update.password = editPassword;
			await updateUser(editingUser.id, update);
			editingUser = null;
			await refresh();
		} catch (e: any) {
			editError = e.message || "Failed to update user";
		}
	}

	async function handleDelete(user: AdminUser) {
		if (!confirm(`Delete user "${user.username}"? This cannot be undone.`)) return;
		error = "";
		try {
			await deleteUser(user.id);
			await refresh();
		} catch (e: any) {
			error = e.message || "Failed to delete user";
		}
	}

	async function startAssign(user: AdminUser) {
		assigningUser = user;
		assignError = "";
		try {
			const resp = await getUserAgents(user.id);
			assignedAgents = resp.agent_names;
		} catch (e: any) {
			assignError = e.message || "Failed to load assignments";
		}
	}

	function toggleAgent(name: string) {
		if (assignedAgents.includes(name)) {
			assignedAgents = assignedAgents.filter((a) => a !== name);
		} else {
			assignedAgents = [...assignedAgents, name];
		}
	}

	async function handleSaveAgents() {
		if (!assigningUser) return;
		assignError = "";
		try {
			await setUserAgents(assigningUser.id, assignedAgents);
			assigningUser = null;
		} catch (e: any) {
			assignError = e.message || "Failed to save assignments";
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return "-";
		return new Date(iso).toLocaleString();
	}
</script>

<div class="flex h-screen flex-col">
	<header class="flex items-center gap-3 border-b border-zinc-800 px-4 py-3">
		<a href="{base}/chat" class="text-zinc-400 hover:text-zinc-200" aria-label="Back to chat">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="20"
				height="20"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<polyline points="15 18 9 12 15 6" />
			</svg>
		</a>
		<h1 class="text-sm font-semibold">Users</h1>

		<div class="flex-1"></div>

		<div class="flex items-center gap-2">
			<a href="{base}/admin/config">
				<Button variant="ghost" size="sm" class="text-zinc-400">Config</Button>
			</a>
			<a href="{base}/admin/cron">
				<Button variant="ghost" size="sm" class="text-zinc-400">Cron</Button>
			</a>
			<Button
				size="sm"
				onclick={() => {
					showCreate = true;
					createError = "";
				}}>New User</Button
			>
		</div>
	</header>

	{#if error}
		<div class="border-b border-red-800 bg-red-950/50 px-4 py-2 text-sm text-red-300">
			{error}
		</div>
	{/if}

	<div class="flex-1 overflow-auto p-6">
		{#if loading}
			<div class="py-12 text-center text-zinc-500">Loading users...</div>
		{:else}
			<div class="mx-auto max-w-5xl space-y-6">
				<!-- Create user form -->
				{#if showCreate}
					<div class="rounded-lg border border-zinc-700 bg-zinc-900 p-4">
						<h3 class="mb-3 text-sm font-semibold text-zinc-200">Create User</h3>
						{#if createError}
							<div class="mb-3 text-sm text-red-400">{createError}</div>
						{/if}
						<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
							<input
								type="text"
								placeholder="Username"
								bind:value={newUsername}
								class="rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-200 outline-none focus:border-zinc-500"
							/>
							<input
								type="password"
								placeholder="Password (min 8 chars)"
								bind:value={newPassword}
								class="rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-200 outline-none focus:border-zinc-500"
							/>
							<input
								type="text"
								placeholder="Display name (optional)"
								bind:value={newDisplayName}
								class="rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-200 outline-none focus:border-zinc-500"
							/>
							<label class="flex items-center gap-2 text-sm text-zinc-300">
								<input type="checkbox" bind:checked={newIsAdmin} />
								Admin
							</label>
						</div>
						<div class="mt-3 flex justify-end gap-2">
							<Button
								variant="ghost"
								size="sm"
								class="text-zinc-400"
								onclick={() => (showCreate = false)}>Cancel</Button
							>
							<Button size="sm" onclick={handleCreate}>Create</Button>
						</div>
					</div>
				{/if}

				<!-- Edit user form -->
				{#if editingUser}
					<div class="rounded-lg border border-zinc-700 bg-zinc-900 p-4">
						<h3 class="mb-3 text-sm font-semibold text-zinc-200">
							Edit: {editingUser.username}
						</h3>
						{#if editError}
							<div class="mb-3 text-sm text-red-400">{editError}</div>
						{/if}
						<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
							<input
								type="text"
								placeholder="Display name"
								bind:value={editDisplayName}
								class="rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-200 outline-none focus:border-zinc-500"
							/>
							<input
								type="password"
								placeholder="New password (leave empty to keep)"
								bind:value={editPassword}
								class="rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-200 outline-none focus:border-zinc-500"
							/>
							<label class="flex items-center gap-2 text-sm text-zinc-300">
								<input type="checkbox" bind:checked={editIsAdmin} />
								Admin
							</label>
						</div>
						<div class="mt-3 flex justify-end gap-2">
							<Button
								variant="ghost"
								size="sm"
								class="text-zinc-400"
								onclick={() => (editingUser = null)}>Cancel</Button
							>
							<Button size="sm" onclick={handleEdit}>Save</Button>
						</div>
					</div>
				{/if}

				<!-- Agent assignment -->
				{#if assigningUser}
					<div class="rounded-lg border border-zinc-700 bg-zinc-900 p-4">
						<h3 class="mb-3 text-sm font-semibold text-zinc-200">
							Agent Access: {assigningUser.username}
						</h3>
						{#if assignError}
							<div class="mb-3 text-sm text-red-400">{assignError}</div>
						{/if}
						<div class="flex flex-wrap gap-2">
							{#each agents as agent}
								<button
									class="rounded border px-3 py-1.5 text-sm transition {assignedAgents.includes(
										agent.name,
									)
										? 'border-emerald-600 bg-emerald-950/50 text-emerald-300'
										: 'border-zinc-700 text-zinc-400 hover:border-zinc-500'}"
									onclick={() => toggleAgent(agent.name)}
								>
									{agent.name}
								</button>
							{/each}
							{#if agents.length === 0}
								<span class="text-sm text-zinc-500">No agents available</span>
							{/if}
						</div>
						<div class="mt-3 flex justify-end gap-2">
							<Button
								variant="ghost"
								size="sm"
								class="text-zinc-400"
								onclick={() => (assigningUser = null)}>Cancel</Button
							>
							<Button size="sm" onclick={handleSaveAgents}>Save</Button>
						</div>
					</div>
				{/if}

				<!-- Users table -->
				<div class="rounded-lg border border-zinc-800">
					<table class="w-full text-sm">
						<thead class="bg-zinc-900/50">
							<tr
								class="text-left text-xs font-medium uppercase tracking-wider text-zinc-500"
							>
								<th class="px-4 py-2">Username</th>
								<th class="px-4 py-2">Display Name</th>
								<th class="px-4 py-2">Role</th>
								<th class="px-4 py-2">Created</th>
								<th class="px-4 py-2">Last Login</th>
								<th class="px-4 py-2 text-right">Actions</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-zinc-800/50">
							{#each users as user}
								<tr class="hover:bg-zinc-900/30">
									<td class="px-4 py-2 font-medium text-zinc-200">{user.username}</td>
									<td class="px-4 py-2 text-zinc-400">{user.display_name}</td>
									<td class="px-4 py-2">
										{#if user.is_admin}
											<span
												class="rounded bg-amber-950/50 px-2 py-0.5 text-xs text-amber-400"
												>Admin</span
											>
										{:else}
											<span class="text-xs text-zinc-500">User</span>
										{/if}
									</td>
									<td class="px-4 py-2 text-xs text-zinc-500"
										>{formatDate(user.created_at)}</td
									>
									<td class="px-4 py-2 text-xs text-zinc-500"
										>{formatDate(user.last_login)}</td
									>
									<td class="px-4 py-2 text-right">
										<div class="flex justify-end gap-1">
											<button
												class="rounded px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-800"
												onclick={() => startEdit(user)}
											>
												Edit
											</button>
											<button
												class="rounded px-2 py-1 text-xs text-blue-400 hover:bg-blue-950/50"
												onclick={() => startAssign(user)}
											>
												Agents
											</button>
											{#if user.id !== auth.user?.id}
												<button
													class="rounded px-2 py-1 text-xs text-red-400 hover:bg-red-950/50"
													onclick={() => handleDelete(user)}
												>
													Delete
												</button>
											{/if}
										</div>
									</td>
								</tr>
							{/each}
							{#if users.length === 0}
								<tr>
									<td colspan="6" class="py-8 text-center text-sm text-zinc-500"
										>No users found</td
									>
								</tr>
							{/if}
						</tbody>
					</table>
				</div>
			</div>
		{/if}
	</div>
</div>
