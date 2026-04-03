<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";
	import { logout, getAgents, type Agent } from "$lib/api.js";
	import { chat } from "$lib/chat.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import AgentSidebar from "$lib/components/chat/AgentSidebar.svelte";
	import MessageList from "$lib/components/chat/MessageList.svelte";
	import ChatInput from "$lib/components/chat/ChatInput.svelte";

	let agents = $state<Agent[]>([]);
	let sidebarCollapsed = $state(false);

	$effect(() => {
		if (!auth.loading && !auth.isAuthenticated) {
			goto(`${base}/login`);
		}
	});

	$effect(() => {
		if (auth.isAuthenticated) {
			chat.init();
			getAgents()
				.then((list) => {
					agents = list;
					// Auto-select first agent if none selected
					if (list.length > 0 && !chat.activeAgent) {
						chat.switchAgent(list[0].name);
					}
				})
				.catch(() => {
					// Silently handle — sidebar will show empty
				});
		}

		return () => {
			chat.destroy();
		};
	});

	async function handleLogout() {
		chat.destroy();
		await logout();
		auth.user = null;
		goto(`${base}/login`);
	}

	function handleSelectAgent(name: string) {
		chat.switchAgent(name);
		// Uncollapse sidebar on mobile after selection? No, collapse it
		if (window.innerWidth < 768) {
			sidebarCollapsed = true;
		}
	}

	function handleSend(content: string) {
		chat.sendMessage(content);
	}

	function handleAbort() {
		chat.abort();
	}
</script>

<div class="flex h-screen">
	<AgentSidebar
		{agents}
		activeAgent={chat.activeAgent}
		connectionState={chat.connectionState}
		onSelectAgent={handleSelectAgent}
		onCollapse={() => (sidebarCollapsed = true)}
		collapsed={sidebarCollapsed}
	/>

	<main class="flex min-w-0 flex-1 flex-col">
		<header class="flex items-center gap-3 border-b border-zinc-800 px-4 py-3">
			{#if sidebarCollapsed}
				<button
					class="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
					onclick={() => (sidebarCollapsed = false)}
					aria-label="Open sidebar"
				>
					<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
				</button>
			{/if}

			{#if chat.activeAgent}
				<div class="flex items-center gap-2">
					<div class="flex h-7 w-7 items-center justify-center rounded-md bg-zinc-700 text-xs font-medium text-zinc-300">
						{chat.activeAgent.charAt(0).toUpperCase()}
					</div>
					<h2 class="text-sm font-semibold">{chat.activeAgent}</h2>
				</div>
			{:else}
				<h2 class="text-sm font-semibold text-zinc-400">Select an agent</h2>
			{/if}

			<div class="flex-1"></div>

			{#if auth.user}
				<div class="flex items-center gap-2">
					<span class="text-xs text-zinc-500">{auth.user.username}</span>
					<Button variant="ghost" size="sm" class="text-zinc-400" onclick={handleLogout}>
						Sign out
					</Button>
				</div>
			{/if}
		</header>

		{#if chat.activeAgent}
			<MessageList
				messages={chat.messages}
				streamingContent={chat.streamingContent}
				streamingToolActivity={chat.streamingToolActivity}
				isStreaming={chat.isStreaming}
			/>

			<ChatInput
				disabled={chat.connectionState !== "connected"}
				isStreaming={chat.isStreaming}
				agentName={chat.activeAgent ?? ""}
				onSend={handleSend}
				onAbort={handleAbort}
			/>
		{:else}
			<div class="flex flex-1 items-center justify-center">
				<div class="text-center">
					<h3 class="text-xl font-medium text-zinc-300">Welcome to Botwerk</h3>
					<p class="mt-2 text-sm text-zinc-500">Select an agent to start chatting.</p>
				</div>
			</div>
		{/if}
	</main>
</div>
