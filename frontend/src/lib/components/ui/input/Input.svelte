<script lang="ts">
	import type { HTMLInputAttributes } from "svelte/elements";
	import { cn } from "$lib/utils/index.js";

	interface InputProps extends HTMLInputAttributes {
		class?: string;
	}

	let { class: className, ...restProps }: InputProps = $props();
</script>

<input
	class={cn(
		"flex h-9 w-full rounded-md border border-zinc-800 bg-transparent px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-zinc-50 placeholder:text-zinc-400 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-300 disabled:cursor-not-allowed disabled:opacity-50",
		className
	)}
	{...restProps}
/>
