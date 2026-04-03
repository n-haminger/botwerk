<script lang="ts">
	import "../app.css";
	import { auth } from "$lib/stores.js";
	import { getMe } from "$lib/api.js";
	import type { Snippet } from "svelte";

	let { children }: { children: Snippet } = $props();

	$effect(() => {
		getMe()
			.then((user) => {
				auth.user = user;
			})
			.catch(() => {
				auth.user = null;
			})
			.finally(() => {
				auth.loading = false;
			});
	});
</script>

<div class="min-h-screen bg-zinc-950 text-zinc-100">
	{@render children()}
</div>
