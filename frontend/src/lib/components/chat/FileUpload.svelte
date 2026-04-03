<script lang="ts">
	import { uploadFile, type FileRecord } from "$lib/api.js";

	let {
		agentName = "",
		disabled = false,
		onFileUploaded,
	}: {
		agentName?: string;
		disabled?: boolean;
		onFileUploaded?: (file: FileRecord) => void;
	} = $props();

	let isDragging = $state(false);
	let isUploading = $state(false);
	let uploadProgress = $state("");
	let errorMessage = $state("");
	let previewUrl = $state<string | null>(null);
	let previewName = $state("");
	let fileInputEl = $state<HTMLInputElement | null>(null);

	function handleDragOver(e: DragEvent) {
		e.preventDefault();
		if (!disabled) isDragging = true;
	}

	function handleDragLeave(e: DragEvent) {
		e.preventDefault();
		isDragging = false;
	}

	async function handleDrop(e: DragEvent) {
		e.preventDefault();
		isDragging = false;
		if (disabled || !e.dataTransfer?.files.length) return;
		await processFile(e.dataTransfer.files[0]);
	}

	function handleClick() {
		if (!disabled && fileInputEl) fileInputEl.click();
	}

	async function handleFileSelect(e: Event) {
		const input = e.target as HTMLInputElement;
		if (!input.files?.length) return;
		await processFile(input.files[0]);
		input.value = "";
	}

	async function processFile(file: File) {
		errorMessage = "";
		previewName = file.name;

		// Show local preview for images.
		if (file.type.startsWith("image/")) {
			previewUrl = URL.createObjectURL(file);
		} else {
			previewUrl = null;
		}

		isUploading = true;
		uploadProgress = "Uploading...";

		try {
			const result = await uploadFile(file, agentName);
			uploadProgress = "";
			onFileUploaded?.(result);
		} catch (err) {
			errorMessage = err instanceof Error ? err.message : "Upload failed";
		} finally {
			isUploading = false;
			if (previewUrl) {
				URL.revokeObjectURL(previewUrl);
				previewUrl = null;
			}
			previewName = "";
		}
	}
</script>

<!-- Hidden file input -->
<input
	bind:this={fileInputEl}
	type="file"
	class="hidden"
	onchange={handleFileSelect}
/>

<!-- Upload button (sits in the input area) -->
<button
	class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-30"
	{disabled}
	onclick={handleClick}
	aria-label="Upload file"
	title="Upload file"
>
	<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
</button>

<!-- Drag overlay (rendered at the chat area level via slot/portal) -->
{#if isDragging}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="pointer-events-auto fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/80 backdrop-blur-sm"
		ondragover={handleDragOver}
		ondragleave={handleDragLeave}
		ondrop={handleDrop}
	>
		<div class="rounded-2xl border-2 border-dashed border-zinc-500 p-12 text-center">
			<svg class="mx-auto h-12 w-12 text-zinc-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
				<path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
			</svg>
			<p class="mt-3 text-lg text-zinc-300">Drop file to upload</p>
		</div>
	</div>
{/if}

<!-- Upload progress indicator -->
{#if isUploading}
	<div class="absolute bottom-full left-0 right-0 mb-2 mx-4">
		<div class="flex items-center gap-2 rounded-lg bg-zinc-800 px-3 py-2 text-xs text-zinc-300">
			<svg class="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
				<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
			</svg>
			{#if previewUrl}
				<img src={previewUrl} alt="" class="h-6 w-6 rounded object-cover" />
			{/if}
			<span class="truncate">{previewName}</span>
			<span class="ml-auto text-zinc-500">{uploadProgress}</span>
		</div>
	</div>
{/if}

{#if errorMessage}
	<div class="absolute bottom-full left-0 right-0 mb-2 mx-4">
		<div class="rounded-lg bg-red-900/50 px-3 py-2 text-xs text-red-300">
			{errorMessage}
			<button class="ml-2 underline" onclick={() => (errorMessage = "")}>dismiss</button>
		</div>
	</div>
{/if}
