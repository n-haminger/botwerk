<script lang="ts">
	import type { Agent } from "$lib/api.js";
	import type { ConnectionState } from "$lib/websocket.js";

	let {
		agents,
		activeAgent,
		connectionState,
		onSelectAgent,
		onCollapse,
		collapsed = false,
	}: {
		agents: Agent[];
		activeAgent: string | null;
		connectionState: ConnectionState;
		onSelectAgent: (name: string) => void;
		onCollapse?: () => void;
		collapsed?: boolean;
	} = $props();

	const connectionColor = $derived(
		connectionState === "connected"
			? "bg-emerald-500"
			: connectionState === "connecting"
				? "bg-amber-500 animate-pulse"
				: "bg-zinc-600",
	);

	const connectionLabel = $derived(
		connectionState === "connected"
			? "Connected"
			: connectionState === "connecting"
				? "Connecting..."
				: "Disconnected",
	);
</script>

<aside
	class="flex flex-col border-r border-zinc-800 bg-zinc-900/50 transition-all duration-200 {collapsed
		? 'w-0 overflow-hidden border-r-0'
		: 'w-64'}"
>
	<div class="flex items-center justify-between border-b border-zinc-800 p-4">
		<h1 class="text-lg font-semibold">Botwerk</h1>
		{#if onCollapse}
			<button
				class="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
				onclick={onCollapse}
				aria-label="Collapse sidebar"
			>
				<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>
			</button>
		{/if}
	</div>

	<div class="flex-1 overflow-y-auto p-4">
		<div class="mb-3 flex items-center justify-between">
			<h2 class="text-xs font-semibold uppercase tracking-wider text-zinc-400">Agents</h2>
			<div class="flex items-center gap-1.5">
				<div class="h-2 w-2 rounded-full {connectionColor}"></div>
				<span class="text-xs text-zinc-500">{connectionLabel}</span>
			</div>
		</div>

		<div class="space-y-1">
			{#if agents.length === 0}
				<p class="text-sm text-zinc-500">No agents available</p>
			{:else}
				{#each agents as agent}
					<button
						class="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors {agent.name ===
						activeAgent
							? 'bg-zinc-800 text-zinc-100'
							: 'text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200'}"
						onclick={() => onSelectAgent(agent.name)}
					>
						<div
							class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-zinc-700 text-xs font-medium text-zinc-300"
						>
							{(agent.name ?? "?").charAt(0).toUpperCase()}
						</div>
						<span class="truncate">{agent.name}</span>
					</button>
				{/each}
			{/if}
		</div>
	</div>
</aside>
