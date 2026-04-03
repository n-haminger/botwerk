<script lang="ts">
	import type { HTMLAttributes } from "svelte/elements";
	import type { Snippet } from "svelte";
	import { cn } from "$lib/utils/index.js";

	interface CardProps extends HTMLAttributes<HTMLDivElement> {
		class?: string;
		children?: Snippet;
	}

	let { class: className, children, ...restProps }: CardProps = $props();
</script>

<div class={cn("rounded-xl border border-zinc-800 bg-zinc-950 text-zinc-50 shadow", className)} {...restProps}>
	{@render children?.()}
</div>
