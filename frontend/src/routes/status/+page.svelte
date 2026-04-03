<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";
	import {
		getSystemStatus,
		getAgentStatuses,
		getServiceStatus,
		restartAgent,
		restartBotwerk,
		type SystemStatus,
		type AgentStatus,
		type ServiceStatus,
	} from "$lib/api.js";
	import { Button } from "$lib/components/ui/button/index.js";

	let system = $state<SystemStatus | null>(null);
	let agents = $state<AgentStatus[]>([]);
	let service = $state<ServiceStatus | null>(null);
	let loading = $state(true);
	let error = $state("");

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
			const [sys, agts, svc] = await Promise.all([
				getSystemStatus(),
				getAgentStatuses(),
				getServiceStatus(),
			]);
			system = sys;
			agents = agts;
			service = svc;
		} catch (e: any) {
			error = e.message || "Failed to load status";
		} finally {
			loading = false;
		}
	}

	async function handleRestartAgent(name: string) {
		if (!confirm(`Restart agent "${name}"?`)) return;
		error = "";
		try {
			await restartAgent(name);
			await refresh();
		} catch (e: any) {
			error = e.message || "Failed to restart agent";
		}
	}

	async function handleRestartBotwerk() {
		if (!confirm("Restart the botwerk service? This will affect all agents.")) return;
		error = "";
		try {
			await restartBotwerk();
			error = ""; // Clear any previous error
			// Show a success-like message
		} catch (e: any) {
			error = e.message || "Failed to restart botwerk";
		}
	}

	function formatBytes(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1048576) return `${(bytes / 1024).toFixed(0)} KB`;
		if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
		return `${(bytes / 1073741824).toFixed(1)} GB`;
	}

	function formatUptime(seconds: number): string {
		const days = Math.floor(seconds / 86400);
		const hours = Math.floor((seconds % 86400) / 3600);
		const mins = Math.floor((seconds % 3600) / 60);
		if (days > 0) return `${days}d ${hours}h ${mins}m`;
		if (hours > 0) return `${hours}h ${mins}m`;
		return `${mins}m`;
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
		<h1 class="text-sm font-semibold">System Status</h1>

		<div class="flex-1"></div>

		<Button size="sm" variant="ghost" class="text-zinc-400" onclick={refresh}>Refresh</Button>
		<div class="flex items-center gap-2">
			<a href="{base}/terminal">
				<Button variant="ghost" size="sm" class="text-zinc-400">Terminal</Button>
			</a>
			<a href="{base}/files">
				<Button variant="ghost" size="sm" class="text-zinc-400">Files</Button>
			</a>
		</div>
	</header>

	{#if error}
		<div class="border-b border-red-800 bg-red-950/50 px-4 py-2 text-sm text-red-300">
			{error}
		</div>
	{/if}

	<div class="flex-1 overflow-auto p-6">
		{#if loading}
			<div class="py-12 text-center text-zinc-500">Loading system status...</div>
		{:else}
			<div class="mx-auto max-w-5xl space-y-6">
				<!-- System metrics cards -->
				{#if system}
					<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
						<!-- CPU -->
						<div class="rounded-lg border border-zinc-800 p-4">
							<div class="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
								CPU
							</div>
							<div class="text-2xl font-bold text-zinc-100">{system.cpu.percent}%</div>
							<div class="mt-1 text-xs text-zinc-500">{system.cpu.count} cores</div>
							<div class="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-800">
								<div
									class="h-full rounded-full transition-all {system.cpu.percent > 80
										? 'bg-red-500'
										: system.cpu.percent > 50
											? 'bg-amber-500'
											: 'bg-emerald-500'}"
									style="width: {system.cpu.percent}%"
								></div>
							</div>
						</div>

						<!-- Memory -->
						<div class="rounded-lg border border-zinc-800 p-4">
							<div class="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
								Memory
							</div>
							<div class="text-2xl font-bold text-zinc-100">{system.memory.percent}%</div>
							<div class="mt-1 text-xs text-zinc-500">
								{formatBytes(system.memory.used)} / {formatBytes(system.memory.total)}
							</div>
							<div class="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-800">
								<div
									class="h-full rounded-full transition-all {system.memory.percent > 80
										? 'bg-red-500'
										: system.memory.percent > 50
											? 'bg-amber-500'
											: 'bg-emerald-500'}"
									style="width: {system.memory.percent}%"
								></div>
							</div>
						</div>

						<!-- Disk -->
						<div class="rounded-lg border border-zinc-800 p-4">
							<div class="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
								Disk
							</div>
							<div class="text-2xl font-bold text-zinc-100">{system.disk.percent}%</div>
							<div class="mt-1 text-xs text-zinc-500">
								{formatBytes(system.disk.used)} / {formatBytes(system.disk.total)}
							</div>
							<div class="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-800">
								<div
									class="h-full rounded-full transition-all {system.disk.percent > 90
										? 'bg-red-500'
										: system.disk.percent > 70
											? 'bg-amber-500'
											: 'bg-emerald-500'}"
									style="width: {system.disk.percent}%"
								></div>
							</div>
						</div>

						<!-- Uptime -->
						<div class="rounded-lg border border-zinc-800 p-4">
							<div class="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
								Uptime
							</div>
							<div class="text-2xl font-bold text-zinc-100">
								{formatUptime(system.uptime_seconds)}
							</div>
							<div class="mt-1 text-xs text-zinc-500">since boot</div>
						</div>
					</div>
				{/if}

				<!-- Service status -->
				{#if service}
					<div class="rounded-lg border border-zinc-800 p-4">
						<div class="mb-3 flex items-center justify-between">
							<h2 class="text-sm font-semibold text-zinc-200">Botwerk Service</h2>
							<Button
								size="sm"
								variant="ghost"
								class="text-amber-400"
								onclick={handleRestartBotwerk}
							>
								Restart Service
							</Button>
						</div>
						<div class="text-sm text-zinc-400">
							<span class="font-medium text-zinc-300">State:</span>
							{service.active_state}
						</div>
					</div>
				{/if}

				<!-- Agent status -->
				<div class="rounded-lg border border-zinc-800">
					<div class="border-b border-zinc-800 px-4 py-3">
						<h2 class="text-sm font-semibold text-zinc-200">Agents</h2>
					</div>
					{#if agents.length === 0}
						<div class="py-8 text-center text-sm text-zinc-500">No agents configured</div>
					{:else}
						<table class="w-full text-sm">
							<thead class="bg-zinc-900/50">
								<tr class="text-left text-xs font-medium uppercase tracking-wider text-zinc-500">
									<th class="px-4 py-2">Agent</th>
									<th class="px-4 py-2">Status</th>
									<th class="px-4 py-2">User</th>
									<th class="px-4 py-2">CPU</th>
									<th class="px-4 py-2">Memory</th>
									<th class="px-4 py-2">PID</th>
									<th class="px-4 py-2 text-right">Actions</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-zinc-800/50">
								{#each agents as agent}
									<tr class="hover:bg-zinc-900/30">
										<td class="px-4 py-2">
											<div class="flex items-center gap-2">
												<div
													class="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-zinc-700 text-xs font-medium text-zinc-300"
												>
													{agent.name.charAt(0).toUpperCase()}
												</div>
												<span class="font-medium text-zinc-200">{agent.name}</span>
												<span class="text-xs text-zinc-500">({agent.agent_type})</span>
											</div>
										</td>
										<td class="px-4 py-2">
											<span
												class="inline-flex items-center gap-1.5 text-xs {agent.status ===
												'running'
													? 'text-emerald-400'
													: 'text-zinc-500'}"
											>
												<span
													class="h-1.5 w-1.5 rounded-full {agent.status === 'running'
														? 'bg-emerald-500'
														: 'bg-zinc-600'}"
												></span>
												{agent.status}
											</span>
										</td>
										<td class="px-4 py-2 text-xs text-zinc-500">{agent.linux_user}</td>
										<td class="px-4 py-2 text-xs text-zinc-400">{agent.cpu_percent}%</td>
										<td class="px-4 py-2 text-xs text-zinc-400">{agent.memory_mb} MB</td>
										<td class="px-4 py-2 text-xs text-zinc-500">{agent.pid ?? "-"}</td>
										<td class="px-4 py-2 text-right">
											<button
												class="rounded px-2 py-1 text-xs text-amber-400 hover:bg-amber-950/50"
												onclick={() => handleRestartAgent(agent.name)}
											>
												Restart
											</button>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>
