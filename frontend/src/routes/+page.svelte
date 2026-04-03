<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";

	$effect(() => {
		if (auth.loading) return;
		if (auth.isAuthenticated) {
			goto(`${base}/chat`);
		} else {
			goto(`${base}/login`);
		}
	});
</script>

<div class="flex h-screen items-center justify-center">
	<div class="text-zinc-400">Loading...</div>
</div>
