<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";
	import {
		getCronJobs,
		enableCronJob,
		disableCronJob,
		triggerCronJob,
		type CronJob,
	} from "$lib/api.js";
	import { Button } from "$lib/components/ui/button/index.js";

	let jobs = $state<CronJob[]>([]);
	let loading = $state(true);
	let error = $state("");
	let actionMsg = $state("");

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
		actionMsg = "";
		try {
			jobs = await getCronJobs();
		} catch (e: any) {
			error = e.message || "Failed to load cron jobs";
		} finally {
			loading = false;
		}
	}

	async function handleToggle(job: CronJob) {
		error = "";
		actionMsg = "";
		try {
			if (job.enabled) {
				await disableCronJob(job.id);
				actionMsg = `Disabled "${job.title}"`;
			} else {
				await enableCronJob(job.id);
				actionMsg = `Enabled "${job.title}"`;
			}
			await refresh();
		} catch (e: any) {
			error = e.message || "Failed to toggle job";
		}
	}

	async function handleTrigger(job: CronJob) {
		if (!confirm(`Trigger "${job.title}" now?`)) return;
		error = "";
		actionMsg = "";
		try {
			await triggerCronJob(job.id);
			actionMsg = `Triggered "${job.title}"`;
			await refresh();
		} catch (e: any) {
			error = e.message || "Failed to trigger job";
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
		<h1 class="text-sm font-semibold">Cron Jobs</h1>

		<div class="flex-1"></div>

		<div class="flex items-center gap-2">
			<a href="{base}/admin/config">
				<Button variant="ghost" size="sm" class="text-zinc-400">Config</Button>
			</a>
			<a href="{base}/admin/users">
				<Button variant="ghost" size="sm" class="text-zinc-400">Users</Button>
			</a>
			<Button variant="ghost" size="sm" class="text-zinc-400" onclick={refresh}>
				Refresh
			</Button>
		</div>
	</header>

	{#if error}
		<div class="border-b border-red-800 bg-red-950/50 px-4 py-2 text-sm text-red-300">
			{error}
		</div>
	{/if}

	{#if actionMsg}
		<div class="border-b border-emerald-800 bg-emerald-950/50 px-4 py-2 text-sm text-emerald-300">
			{actionMsg}
		</div>
	{/if}

	<div class="flex-1 overflow-auto p-6">
		{#if loading}
			<div class="py-12 text-center text-zinc-500">Loading cron jobs...</div>
		{:else}
			<div class="mx-auto max-w-5xl">
				<div class="rounded-lg border border-zinc-800">
					{#if jobs.length === 0}
						<div class="py-8 text-center text-sm text-zinc-500">No cron jobs configured</div>
					{:else}
						<table class="w-full text-sm">
							<thead class="bg-zinc-900/50">
								<tr
									class="text-left text-xs font-medium uppercase tracking-wider text-zinc-500"
								>
									<th class="px-4 py-2">Job</th>
									<th class="px-4 py-2">Schedule</th>
									<th class="px-4 py-2">Status</th>
									<th class="px-4 py-2">Last Run</th>
									<th class="px-4 py-2">Next Run</th>
									<th class="px-4 py-2 text-right">Actions</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-zinc-800/50">
								{#each jobs as job}
									<tr class="hover:bg-zinc-900/30">
										<td class="px-4 py-2">
											<div class="font-medium text-zinc-200">{job.title}</div>
											<div class="mt-0.5 text-xs text-zinc-500">
												{job.description || job.id}
											</div>
										</td>
										<td class="px-4 py-2">
											<code class="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-300"
												>{job.schedule}</code
											>
										</td>
										<td class="px-4 py-2">
											<span
												class="inline-flex items-center gap-1.5 text-xs {job.enabled
													? 'text-emerald-400'
													: 'text-zinc-500'}"
											>
												<span
													class="h-1.5 w-1.5 rounded-full {job.enabled
														? 'bg-emerald-500'
														: 'bg-zinc-600'}"
												></span>
												{job.enabled ? "Enabled" : "Disabled"}
											</span>
										</td>
										<td class="px-4 py-2 text-xs text-zinc-500">
											<div>{formatDate(job.last_run_at)}</div>
											{#if job.last_run_status}
												<div
													class="mt-0.5 {job.last_run_status === 'ok'
														? 'text-emerald-500'
														: job.last_run_status === 'error'
															? 'text-red-400'
															: 'text-zinc-500'}"
												>
													{job.last_run_status}
												</div>
											{/if}
										</td>
										<td class="px-4 py-2 text-xs text-zinc-500">
											{formatDate(job.next_run)}
										</td>
										<td class="px-4 py-2 text-right">
											<div class="flex justify-end gap-1">
												<button
													class="rounded px-2 py-1 text-xs {job.enabled
														? 'text-amber-400 hover:bg-amber-950/50'
														: 'text-emerald-400 hover:bg-emerald-950/50'}"
													onclick={() => handleToggle(job)}
												>
													{job.enabled ? "Disable" : "Enable"}
												</button>
												<button
													class="rounded px-2 py-1 text-xs text-blue-400 hover:bg-blue-950/50"
													onclick={() => handleTrigger(job)}
												>
													Trigger
												</button>
											</div>
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
