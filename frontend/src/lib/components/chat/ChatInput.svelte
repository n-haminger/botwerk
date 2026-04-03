<script lang="ts">
	let {
		disabled = false,
		isStreaming = false,
		onSend,
		onAbort,
	}: {
		disabled?: boolean;
		isStreaming?: boolean;
		onSend: (content: string) => void;
		onAbort?: () => void;
	} = $props();

	let text = $state("");
	let textareaEl = $state<HTMLTextAreaElement | null>(null);

	function adjustHeight() {
		if (!textareaEl) return;
		textareaEl.style.height = "auto";
		textareaEl.style.height = Math.min(textareaEl.scrollHeight, 200) + "px";
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			send();
		}
	}

	function send() {
		const trimmed = text.trim();
		if (!trimmed || disabled) return;
		onSend(trimmed);
		text = "";
		if (textareaEl) {
			textareaEl.style.height = "auto";
		}
	}
</script>

<div class="border-t border-zinc-800 bg-zinc-950 p-4">
	<div class="mx-auto flex max-w-3xl items-end gap-2">
		<div class="relative flex-1">
			<textarea
				bind:this={textareaEl}
				bind:value={text}
				oninput={adjustHeight}
				onkeydown={handleKeydown}
				disabled={disabled || isStreaming}
				placeholder={isStreaming ? "Waiting for response..." : "Message..."}
				rows={1}
				class="w-full resize-none rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm text-zinc-100 placeholder-zinc-500 outline-none transition-colors focus:border-zinc-500 disabled:cursor-not-allowed disabled:opacity-50"
			></textarea>
		</div>

		{#if isStreaming}
			<button
				class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-red-600 text-white transition-colors hover:bg-red-500"
				onclick={() => onAbort?.()}
				aria-label="Stop generating"
			>
				<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
			</button>
		{:else}
			<button
				class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-900 transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-30"
				disabled={!text.trim() || disabled}
				onclick={send}
				aria-label="Send message"
			>
				<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg>
			</button>
		{/if}
	</div>
</div>
