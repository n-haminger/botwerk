<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";
	import { logout } from "$lib/api.js";
	import { Button } from "$lib/components/ui/button/index.js";

	$effect(() => {
		if (!auth.loading && !auth.isAuthenticated) {
			goto(`${base}/login`);
		}
	});

	async function handleLogout() {
		await logout();
		auth.user = null;
		goto(`${base}/login`);
	}
</script>

<div class="flex h-screen">
	<!-- Sidebar -->
	<aside class="flex w-64 flex-col border-r border-zinc-800 bg-zinc-900/50">
		<div class="flex items-center gap-2 border-b border-zinc-800 p-4">
			<h1 class="text-lg font-semibold">Botwerk</h1>
		</div>

		<div class="flex-1 overflow-y-auto p-4">
			<h2 class="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
				Agents
			</h2>
			<div class="space-y-1">
				<p class="text-sm text-zinc-500">Loading agents...</p>
			</div>
		</div>

		<div class="border-t border-zinc-800 p-4">
			{#if auth.user}
				<div class="mb-3 flex items-center gap-2">
					<div class="flex h-8 w-8 items-center justify-center rounded-full bg-zinc-700 text-sm font-medium">
						{auth.user.username.charAt(0).toUpperCase()}
					</div>
					<div class="flex-1 truncate">
						<p class="text-sm font-medium">{auth.user.username}</p>
						<p class="text-xs text-zinc-400">{auth.user.is_admin ? "Admin" : "User"}</p>
					</div>
				</div>
			{/if}
			<Button variant="ghost" class="w-full justify-start text-zinc-400" onclick={handleLogout}>
				Sign out
			</Button>
		</div>
	</aside>

	<!-- Main content -->
	<main class="flex flex-1 flex-col">
		<header class="flex items-center border-b border-zinc-800 px-6 py-4">
			<h2 class="text-lg font-semibold">Chat</h2>
		</header>

		<div class="flex flex-1 items-center justify-center">
			<div class="text-center">
				<h3 class="text-xl font-medium text-zinc-300">Welcome to Botwerk</h3>
				<p class="mt-2 text-sm text-zinc-500">Select an agent to start chatting.</p>
			</div>
		</div>
	</main>
</div>
