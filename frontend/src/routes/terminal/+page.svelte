<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";
	import { getLinuxUsers, type LinuxUser } from "$lib/api.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { onMount } from "svelte";

	let terminalEl: HTMLDivElement;
	let term: any = null;
	let fitAddon: any = null;
	let ws: WebSocket | null = null;
	let users = $state<LinuxUser[]>([]);
	let selectedUser = $state("");
	let connected = $state(false);
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
			getLinuxUsers()
				.then((list) => {
					users = list;
					if (list.length > 0 && !selectedUser) {
						selectedUser = list[0].username;
					}
				})
				.catch((e) => {
					error = e.message || "Failed to load users";
				});
		}
	});

	onMount(() => {
		return () => {
			disconnect();
			if (term) term.dispose();
		};
	});

	async function initTerminal() {
		if (term) return;
		const { Terminal } = await import("@xterm/xterm");
		const { FitAddon } = await import("@xterm/addon-fit");
		const { WebLinksAddon } = await import("@xterm/addon-web-links");

		// Import xterm CSS
		await import("@xterm/xterm/css/xterm.css");

		term = new Terminal({
			cursorBlink: true,
			fontSize: 14,
			fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
			theme: {
				background: "#09090b",
				foreground: "#e4e4e7",
				cursor: "#e4e4e7",
				selectionBackground: "#3f3f46",
				black: "#09090b",
				red: "#ef4444",
				green: "#22c55e",
				yellow: "#eab308",
				blue: "#3b82f6",
				magenta: "#a855f7",
				cyan: "#06b6d4",
				white: "#e4e4e7",
				brightBlack: "#52525b",
				brightRed: "#f87171",
				brightGreen: "#4ade80",
				brightYellow: "#facc15",
				brightBlue: "#60a5fa",
				brightMagenta: "#c084fc",
				brightCyan: "#22d3ee",
				brightWhite: "#fafafa",
			},
		});

		fitAddon = new FitAddon();
		term.loadAddon(fitAddon);
		term.loadAddon(new WebLinksAddon());
		term.open(terminalEl);
		fitAddon.fit();

		// Handle input
		term.onData((data: string) => {
			if (ws && ws.readyState === WebSocket.OPEN) {
				ws.send(JSON.stringify({ type: "input", data }));
			}
		});

		// Handle resize
		const resizeObserver = new ResizeObserver(() => {
			if (fitAddon) {
				fitAddon.fit();
				if (ws && ws.readyState === WebSocket.OPEN) {
					ws.send(
						JSON.stringify({
							type: "resize",
							cols: term.cols,
							rows: term.rows,
						}),
					);
				}
			}
		});
		resizeObserver.observe(terminalEl);
	}

	async function connect() {
		if (!selectedUser) return;
		error = "";

		await initTerminal();
		if (term) {
			term.clear();
		}

		disconnect();

		const proto = location.protocol === "https:" ? "wss:" : "ws:";
		ws = new WebSocket(`${proto}//${location.host}/ws/terminal`);

		ws.onopen = () => {
			connected = true;
			ws!.send(
				JSON.stringify({
					type: "init",
					user: selectedUser,
					cols: term?.cols || 80,
					rows: term?.rows || 24,
				}),
			);
		};

		ws.onmessage = (event) => {
			const msg = JSON.parse(event.data);
			if (msg.type === "output" && term) {
				term.write(msg.data);
			} else if (msg.type === "exit") {
				connected = false;
				if (term) {
					term.write(`\r\n\x1b[33m[Session exited with code ${msg.code}]\x1b[0m\r\n`);
				}
			} else if (msg.type === "error") {
				error = msg.data;
			}
		};

		ws.onclose = () => {
			connected = false;
		};

		ws.onerror = () => {
			error = "WebSocket connection failed";
			connected = false;
		};
	}

	function disconnect() {
		if (ws) {
			ws.close();
			ws = null;
		}
		connected = false;
	}

	function switchUser() {
		connect();
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
		<h1 class="text-sm font-semibold">Terminal</h1>

		<div class="flex items-center gap-2">
			<select
				bind:value={selectedUser}
				class="rounded-md border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-100 focus:border-zinc-500 focus:outline-none"
			>
				{#each users as user}
					<option value={user.username}>{user.username}</option>
				{/each}
			</select>
			{#if connected}
				<Button size="sm" variant="ghost" class="text-amber-400" onclick={switchUser}>
					Switch
				</Button>
				<Button size="sm" variant="ghost" class="text-red-400" onclick={disconnect}>
					Disconnect
				</Button>
			{:else}
				<Button size="sm" onclick={connect} disabled={!selectedUser}>Connect</Button>
			{/if}
		</div>

		<div class="flex-1"></div>

		<span
			class="inline-flex items-center gap-1.5 text-xs {connected
				? 'text-emerald-400'
				: 'text-zinc-500'}"
		>
			<span
				class="h-1.5 w-1.5 rounded-full {connected ? 'bg-emerald-500' : 'bg-zinc-600'}"
			></span>
			{connected ? "Connected" : "Disconnected"}
		</span>

		<div class="flex items-center gap-2">
			<a href="{base}/files">
				<Button variant="ghost" size="sm" class="text-zinc-400">Files</Button>
			</a>
			<a href="{base}/status">
				<Button variant="ghost" size="sm" class="text-zinc-400">Status</Button>
			</a>
		</div>
	</header>

	{#if error}
		<div
			class="border-b border-red-800 bg-red-950/50 px-4 py-2 text-sm text-red-300"
		>
			{error}
		</div>
	{/if}

	<div class="flex-1 overflow-hidden bg-[#09090b] p-1" bind:this={terminalEl}></div>
</div>
