<script lang="ts">
	import type { ChatMessage } from "$lib/chat.js";

	let {
		messages,
		streamingContent = "",
		streamingToolActivity = "",
		isStreaming = false,
	}: {
		messages: ChatMessage[];
		streamingContent?: string;
		streamingToolActivity?: string;
		isStreaming?: boolean;
	} = $props();

	let containerEl = $state<HTMLDivElement | null>(null);
	let userScrolledUp = $state(false);
	let lastMessageCount = $state(0);

	function handleScroll() {
		if (!containerEl) return;
		const { scrollTop, scrollHeight, clientHeight } = containerEl;
		// User scrolled up if not near bottom (within 100px)
		userScrolledUp = scrollHeight - scrollTop - clientHeight > 100;
	}

	$effect(() => {
		// Re-run on messages change, streaming content change
		const _ = [messages.length, streamingContent, isStreaming];
		void _;

		if (!containerEl || userScrolledUp) return;

		// Use microtask to ensure DOM has updated
		queueMicrotask(() => {
			if (containerEl) {
				containerEl.scrollTop = containerEl.scrollHeight;
			}
		});
	});

	// Reset scroll lock when new message arrives (user sent a message)
	$effect(() => {
		if (messages.length > lastMessageCount) {
			const newest = messages[messages.length - 1];
			if (newest?.role === "user") {
				userScrolledUp = false;
			}
		}
		lastMessageCount = messages.length;
	});

	function escapeHtml(text: string): string {
		return text
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;");
	}

	function renderMarkdown(text: string): string {
		let html = escapeHtml(text);

		// Code blocks (```...```)
		html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_match, _lang, code) => {
			return `<pre class="my-2 overflow-x-auto rounded-md bg-zinc-900 p-3 text-xs"><code>${code.trim()}</code></pre>`;
		});

		// Inline code
		html = html.replace(/`([^`]+)`/g, '<code class="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-300">$1</code>');

		// Bold
		html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

		// Italic
		html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

		// Line breaks
		html = html.replace(/\n/g, "<br>");

		return html;
	}
</script>

<div
	bind:this={containerEl}
	onscroll={handleScroll}
	class="flex-1 overflow-y-auto"
>
	<div class="mx-auto max-w-3xl px-4 py-6 space-y-4">
		{#if messages.length === 0 && !isStreaming}
			<div class="flex h-full items-center justify-center pt-32">
				<div class="text-center">
					<h3 class="text-xl font-medium text-zinc-300">Start a conversation</h3>
					<p class="mt-2 text-sm text-zinc-500">Send a message to begin.</p>
				</div>
			</div>
		{/if}

		{#each messages as message (message.id)}
			{#if message.role === "user"}
				<div class="flex justify-end">
					<div class="max-w-[80%] rounded-2xl rounded-br-sm bg-zinc-700 px-4 py-2.5 text-sm text-zinc-100">
						{@html renderMarkdown(message.content)}
					</div>
				</div>
			{:else if message.role === "system"}
				<div class="flex justify-center">
					<div class="rounded-full bg-zinc-800/50 px-4 py-1.5 text-xs text-zinc-400">
						{message.content}
					</div>
				</div>
			{:else}
				<div class="flex justify-start">
					<div class="max-w-[85%] rounded-2xl rounded-bl-sm bg-zinc-800/60 px-4 py-2.5 text-sm leading-relaxed text-zinc-200">
						{@html renderMarkdown(message.content)}
					</div>
				</div>
			{/if}
		{/each}

		{#if isStreaming}
			<div class="flex justify-start">
				<div class="max-w-[85%] rounded-2xl rounded-bl-sm bg-zinc-800/60 px-4 py-2.5 text-sm leading-relaxed text-zinc-200">
					{#if streamingContent}
						{@html renderMarkdown(streamingContent)}
					{/if}
					<span class="inline-flex items-center gap-0.5 ml-1 align-middle">
						<span class="h-1.5 w-1.5 rounded-full bg-zinc-400 animate-pulse"></span>
						<span class="h-1.5 w-1.5 rounded-full bg-zinc-400 animate-pulse" style="animation-delay: 150ms"></span>
						<span class="h-1.5 w-1.5 rounded-full bg-zinc-400 animate-pulse" style="animation-delay: 300ms"></span>
					</span>
				</div>
			</div>

			{#if streamingToolActivity}
				<div class="ml-2 flex items-center gap-1.5 text-xs text-zinc-500">
					<svg class="h-3 w-3 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
						<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
					</svg>
					<span>{streamingToolActivity}</span>
				</div>
			{/if}
		{/if}
	</div>
</div>
