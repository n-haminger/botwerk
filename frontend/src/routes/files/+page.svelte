<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";
	import {
		getLinuxUsers,
		explorerList,
		explorerRead,
		explorerWrite,
		explorerMkdir,
		explorerDelete,
		explorerDownloadUrl,
		type LinuxUser,
		type FileEntry,
	} from "$lib/api.js";
	import { Button } from "$lib/components/ui/button/index.js";

	let users = $state<LinuxUser[]>([]);
	let selectedUser = $state("");
	let currentPath = $state("/home");
	let entries = $state<FileEntry[]>([]);
	let loading = $state(false);
	let error = $state("");

	// Editor state
	let editingFile = $state<string | null>(null);
	let editorContent = $state("");
	let editorDirty = $state(false);
	let editorLoading = $state(false);

	// Create state
	let showCreate = $state(false);
	let createType = $state<"file" | "dir">("file");
	let createName = $state("");

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
			getLinuxUsers()
				.then((list) => {
					users = list;
					if (list.length > 0 && !selectedUser) {
						selectedUser = list[0].username;
						loadDirectory();
					}
				})
				.catch((e) => {
					error = e.message || "Failed to load users";
				});
		}
	});

	async function loadDirectory() {
		if (!selectedUser) return;
		loading = true;
		error = "";
		editingFile = null;
		try {
			entries = await explorerList(currentPath, selectedUser);
		} catch (e: any) {
			error = e.message || "Failed to list directory";
			entries = [];
		} finally {
			loading = false;
		}
	}

	function navigate(entry: FileEntry) {
		if (entry.type === "dir" || entry.type === "symlink") {
			currentPath = currentPath === "/" ? `/${entry.name}` : `${currentPath}/${entry.name}`;
			loadDirectory();
		} else {
			openFile(entry);
		}
	}

	function navigateUp() {
		const parts = currentPath.split("/").filter(Boolean);
		parts.pop();
		currentPath = parts.length > 0 ? "/" + parts.join("/") : "/";
		loadDirectory();
	}

	function navigateTo(index: number) {
		const parts = currentPath.split("/").filter(Boolean);
		currentPath = "/" + parts.slice(0, index + 1).join("/");
		loadDirectory();
	}

	async function openFile(entry: FileEntry) {
		if (entry.size > 1048576) {
			error = "File too large to edit (max 1MB)";
			return;
		}
		editorLoading = true;
		error = "";
		try {
			const filePath =
				currentPath === "/" ? `/${entry.name}` : `${currentPath}/${entry.name}`;
			const result = await explorerRead(filePath, selectedUser);
			editingFile = filePath;
			editorContent = result.content;
			editorDirty = false;
		} catch (e: any) {
			error = e.message || "Failed to read file";
		} finally {
			editorLoading = false;
		}
	}

	async function saveFile() {
		if (!editingFile) return;
		editorLoading = true;
		error = "";
		try {
			await explorerWrite(editingFile, selectedUser, editorContent);
			editorDirty = false;
		} catch (e: any) {
			error = e.message || "Failed to save file";
		} finally {
			editorLoading = false;
		}
	}

	async function handleCreate() {
		if (!createName) return;
		error = "";
		const fullPath =
			currentPath === "/"
				? `/${createName}`
				: `${currentPath}/${createName}`;
		try {
			if (createType === "dir") {
				await explorerMkdir(fullPath, selectedUser);
			} else {
				await explorerWrite(fullPath, selectedUser, "");
			}
			showCreate = false;
			createName = "";
			await loadDirectory();
		} catch (e: any) {
			error = e.message || "Failed to create";
		}
	}

	async function handleDelete(entry: FileEntry) {
		const fullPath =
			currentPath === "/"
				? `/${entry.name}`
				: `${currentPath}/${entry.name}`;
		if (!confirm(`Delete "${entry.name}"? This cannot be undone.`)) return;
		error = "";
		try {
			await explorerDelete(fullPath, selectedUser);
			await loadDirectory();
		} catch (e: any) {
			error = e.message || "Failed to delete";
		}
	}

	function handleDownload(entry: FileEntry) {
		const fullPath =
			currentPath === "/"
				? `/${entry.name}`
				: `${currentPath}/${entry.name}`;
		window.open(explorerDownloadUrl(fullPath, selectedUser), "_blank");
	}

	function switchUser() {
		const user = users.find((u) => u.username === selectedUser);
		if (user) {
			currentPath = user.home || "/home";
		}
		loadDirectory();
	}

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
		return `${(bytes / 1073741824).toFixed(1)} GB`;
	}

	function formatDate(timestamp: number): string {
		if (!timestamp) return "-";
		return new Date(timestamp * 1000).toLocaleString();
	}

	const breadcrumbs = $derived(currentPath.split("/").filter(Boolean));
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
		<h1 class="text-sm font-semibold">Files</h1>

		<div class="flex items-center gap-2">
			<select
				bind:value={selectedUser}
				onchange={switchUser}
				class="rounded-md border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-100 focus:border-zinc-500 focus:outline-none"
			>
				{#each users as user}
					<option value={user.username}>{user.username}</option>
				{/each}
			</select>
		</div>

		<div class="flex-1"></div>

		<div class="flex items-center gap-2">
			<Button size="sm" variant="ghost" class="text-zinc-400" onclick={() => (showCreate = true)}>
				New
			</Button>
			<a href="{base}/terminal">
				<Button variant="ghost" size="sm" class="text-zinc-400">Terminal</Button>
			</a>
			<a href="{base}/status">
				<Button variant="ghost" size="sm" class="text-zinc-400">Status</Button>
			</a>
		</div>
	</header>

	{#if error}
		<div class="border-b border-red-800 bg-red-950/50 px-4 py-2 text-sm text-red-300">
			{error}
		</div>
	{/if}

	<!-- Breadcrumb -->
	<div class="flex items-center gap-1 border-b border-zinc-800 px-4 py-2 text-sm">
		<button class="text-zinc-400 hover:text-zinc-200" onclick={() => { currentPath = "/"; loadDirectory(); }}>
			/
		</button>
		{#each breadcrumbs as crumb, i}
			<span class="text-zinc-600">/</span>
			<button
				class="text-zinc-400 hover:text-zinc-200 {i === breadcrumbs.length - 1 ? 'font-medium text-zinc-200' : ''}"
				onclick={() => navigateTo(i)}
			>
				{crumb}
			</button>
		{/each}
	</div>

	<div class="flex flex-1 overflow-hidden">
		<!-- File list -->
		<div class="flex-1 overflow-auto {editingFile ? 'w-1/2 border-r border-zinc-800' : ''}">
			{#if loading}
				<div class="py-12 text-center text-zinc-500">Loading...</div>
			{:else if entries.length === 0}
				<div class="py-12 text-center text-zinc-500">Empty directory</div>
			{:else}
				<table class="w-full text-sm">
					<thead class="sticky top-0 bg-zinc-950/95">
						<tr class="text-left text-xs font-medium uppercase tracking-wider text-zinc-500">
							<th class="px-4 py-2">Name</th>
							<th class="px-4 py-2">Size</th>
							<th class="px-4 py-2">Permissions</th>
							<th class="px-4 py-2">Modified</th>
							<th class="px-4 py-2 text-right">Actions</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-zinc-800/50">
						<!-- Parent directory -->
						{#if currentPath !== "/"}
							<tr
								class="cursor-pointer hover:bg-zinc-900/30"
								ondblclick={navigateUp}
							>
								<td class="px-4 py-2">
									<div class="flex items-center gap-2 text-zinc-400">
										<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>
										..
									</div>
								</td>
								<td></td><td></td><td></td><td></td>
							</tr>
						{/if}
						{#each entries as entry}
							<tr class="cursor-pointer hover:bg-zinc-900/30" ondblclick={() => navigate(entry)}>
								<td class="px-4 py-2">
									<div class="flex items-center gap-2">
										{#if entry.type === "dir"}
											<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-blue-400"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
										{:else if entry.type === "symlink"}
											<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-purple-400"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
										{:else}
											<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-zinc-400"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
										{/if}
										<span class="text-zinc-200">{entry.name}</span>
									</div>
								</td>
								<td class="px-4 py-2 text-zinc-500">{entry.type === "dir" ? "-" : formatSize(entry.size)}</td>
								<td class="px-4 py-2 font-mono text-xs text-zinc-500">{entry.permissions}</td>
								<td class="px-4 py-2 text-xs text-zinc-500">{formatDate(entry.modified_at)}</td>
								<td class="px-4 py-2 text-right">
									<div class="flex items-center justify-end gap-1">
										{#if entry.type === "file"}
											<button
												class="rounded px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-800"
												onclick={() => handleDownload(entry)}
											>
												Download
											</button>
										{/if}
										<button
											class="rounded px-2 py-1 text-xs text-red-400 hover:bg-red-950/50"
											onclick={() => handleDelete(entry)}
										>
											Delete
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>

		<!-- Editor panel -->
		{#if editingFile}
			<div class="flex w-1/2 flex-col">
				<div class="flex items-center gap-2 border-b border-zinc-800 px-4 py-2">
					<span class="flex-1 truncate text-sm text-zinc-300">{editingFile}</span>
					{#if editorDirty}
						<span class="text-xs text-amber-400">unsaved</span>
					{/if}
					<Button size="sm" onclick={saveFile} disabled={!editorDirty || editorLoading}>
						Save
					</Button>
					<button
						class="rounded p-1 text-zinc-400 hover:bg-zinc-800"
						onclick={() => (editingFile = null)}
						aria-label="Close editor"
					>
						<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
					</button>
				</div>
				{#if editorLoading}
					<div class="flex flex-1 items-center justify-center text-zinc-500">Loading...</div>
				{:else}
					<textarea
						class="flex-1 resize-none border-none bg-zinc-950 p-4 font-mono text-sm text-zinc-200 focus:outline-none"
						bind:value={editorContent}
						oninput={() => (editorDirty = true)}
						spellcheck="false"
					></textarea>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Create dialog -->
	{#if showCreate}
		<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
			<div class="w-full max-w-sm rounded-lg border border-zinc-700 bg-zinc-900 p-6 shadow-xl">
				<h2 class="mb-4 text-lg font-semibold text-zinc-100">Create New</h2>
				<div class="mb-3 flex gap-2">
					<button
						class="flex-1 rounded-md py-2 text-sm {createType === 'file'
							? 'bg-zinc-700 text-zinc-100'
							: 'bg-zinc-800 text-zinc-400'}"
						onclick={() => (createType = "file")}
					>
						File
					</button>
					<button
						class="flex-1 rounded-md py-2 text-sm {createType === 'dir'
							? 'bg-zinc-700 text-zinc-100'
							: 'bg-zinc-800 text-zinc-400'}"
						onclick={() => (createType = "dir")}
					>
						Directory
					</button>
				</div>
				<input
					type="text"
					bind:value={createName}
					placeholder="Name"
					class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
				/>
				<div class="mt-4 flex justify-end gap-2">
					<Button variant="ghost" size="sm" class="text-zinc-400" onclick={() => { showCreate = false; createName = ""; }}>
						Cancel
					</Button>
					<Button size="sm" onclick={handleCreate} disabled={!createName}>Create</Button>
				</div>
			</div>
		</div>
	{/if}
</div>
