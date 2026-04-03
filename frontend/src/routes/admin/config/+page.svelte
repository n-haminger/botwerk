<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";
	import { getConfig, updateConfig } from "$lib/api.js";
	import { Button } from "$lib/components/ui/button/index.js";

	let configText = $state("");
	let loading = $state(true);
	let saving = $state(false);
	let error = $state("");
	let success = $state("");
	let parseError = $state("");

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
			loadConfig();
		}
	});

	async function loadConfig() {
		loading = true;
		error = "";
		success = "";
		try {
			const data = await getConfig();
			configText = JSON.stringify(data.config, null, 2);
		} catch (e: any) {
			error = e.message || "Failed to load config";
		} finally {
			loading = false;
		}
	}

	function validateJson() {
		parseError = "";
		try {
			JSON.parse(configText);
			return true;
		} catch {
			parseError = "Invalid JSON syntax";
			return false;
		}
	}

	async function handleSave() {
		if (!validateJson()) return;
		saving = true;
		error = "";
		success = "";
		try {
			const parsed = JSON.parse(configText);
			const result = await updateConfig(parsed);
			configText = JSON.stringify(result.config, null, 2);
			success = "Config saved successfully. Restart may be needed for changes to take effect.";
		} catch (e: any) {
			error = e.message || "Failed to save config";
		} finally {
			saving = false;
		}
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
		<h1 class="text-sm font-semibold">Config</h1>

		<div class="flex-1"></div>

		<div class="flex items-center gap-2">
			<a href="{base}/admin/users">
				<Button variant="ghost" size="sm" class="text-zinc-400">Users</Button>
			</a>
			<a href="{base}/admin/cron">
				<Button variant="ghost" size="sm" class="text-zinc-400">Cron</Button>
			</a>
			<Button variant="ghost" size="sm" class="text-zinc-400" onclick={loadConfig}>
				Reload
			</Button>
		</div>
	</header>

	{#if error}
		<div class="border-b border-red-800 bg-red-950/50 px-4 py-2 text-sm text-red-300">
			{error}
		</div>
	{/if}

	{#if success}
		<div class="border-b border-emerald-800 bg-emerald-950/50 px-4 py-2 text-sm text-emerald-300">
			{success}
		</div>
	{/if}

	<div class="flex-1 overflow-auto p-6">
		{#if loading}
			<div class="py-12 text-center text-zinc-500">Loading config...</div>
		{:else}
			<div class="mx-auto max-w-4xl space-y-4">
				<div class="rounded-lg border border-zinc-800">
					<div class="flex items-center justify-between border-b border-zinc-800 px-4 py-2">
						<span class="text-xs font-medium text-zinc-400">config.json</span>
						{#if parseError}
							<span class="text-xs text-red-400">{parseError}</span>
						{/if}
					</div>
					<textarea
						class="h-[600px] w-full resize-y bg-transparent p-4 font-mono text-sm text-zinc-200 outline-none"
						bind:value={configText}
						oninput={() => { parseError = ""; success = ""; }}
						spellcheck="false"
					></textarea>
				</div>

				<div class="flex justify-end">
					<Button
						size="sm"
						disabled={saving || !!parseError}
						onclick={handleSave}
					>
						{saving ? "Saving..." : "Save Config"}
					</Button>
				</div>
			</div>
		{/if}
	</div>
</div>
