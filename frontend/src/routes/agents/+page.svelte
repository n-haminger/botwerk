<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";
	import {
		getAgents,
		createAgent,
		updateAgent,
		deleteAgent,
		startAgent,
		stopAgent,
		getAgentHierarchy,
		getPermissionTemplates,
		type Agent,
		type AgentCreate,
		type AgentUpdate,
		type AgentHierarchyNode,
		type PermissionTemplate,
	} from "$lib/api.js";
	import { Button } from "$lib/components/ui/button/index.js";

	let agents = $state<Agent[]>([]);
	let hierarchy = $state<AgentHierarchyNode[]>([]);
	let templates = $state<PermissionTemplate[]>([]);
	let loading = $state(true);
	let error = $state("");
	let showCreate = $state(false);
	let editingAgent = $state<Agent | null>(null);
	let activeTab = $state<"list" | "hierarchy">("list");

	// Create form state
	let newName = $state("");
	let newProvider = $state("");
	let newModel = $state("");
	let newAgentType = $state("worker");
	let newLinuxUser = $state(false);
	let newLinuxUserName = $state("");
	let newTemplate = $state("");
	let newTrustLevel = $state("restricted");

	// Edit form state
	let editProvider = $state("");
	let editModel = $state("");
	let editAgentType = $state("worker");
	let editTrustLevel = $state("restricted");
	let editManager = $state("");
	let editWorkers = $state("");

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
		try {
			const [agentList, tmpl] = await Promise.all([
				getAgents(),
				getPermissionTemplates(),
			]);
			agents = agentList;
			templates = tmpl;
			try {
				const h = await getAgentHierarchy();
				hierarchy = h.roots;
			} catch {
				hierarchy = [];
			}
		} catch (e: any) {
			error = e.message || "Failed to load agents";
		} finally {
			loading = false;
		}
	}

	async function handleCreate() {
		error = "";
		const data: AgentCreate = { name: newName };
		if (newProvider) data.provider = newProvider;
		if (newModel) data.model = newModel;
		if (newAgentType !== "worker") data.agent_type = newAgentType;
		if (newLinuxUser) {
			data.linux_user = true;
			if (newLinuxUserName) data.linux_user_name = newLinuxUserName;
		}
		if (newTemplate) data.permission_template = newTemplate;
		if (newTrustLevel !== "restricted") data.trust_level = newTrustLevel;

		try {
			await createAgent(data);
			showCreate = false;
			resetCreateForm();
			await refresh();
		} catch (e: any) {
			error = e.message || "Failed to create agent";
		}
	}

	function resetCreateForm() {
		newName = "";
		newProvider = "";
		newModel = "";
		newAgentType = "worker";
		newLinuxUser = false;
		newLinuxUserName = "";
		newTemplate = "";
		newTrustLevel = "restricted";
	}

	function openEdit(agent: Agent) {
		editingAgent = agent;
		editProvider = agent.provider || "";
		editModel = agent.model || "";
		editAgentType = agent.agent_type || "worker";
		editTrustLevel = agent.trust_level || "restricted";
		editManager = agent.manager || "";
		editWorkers = (agent.workers || []).join(", ");
	}

	async function handleUpdate() {
		if (!editingAgent) return;
		error = "";
		const data: AgentUpdate = {};
		if (editProvider) data.provider = editProvider;
		if (editModel) data.model = editModel;
		if (editAgentType) data.agent_type = editAgentType;
		if (editTrustLevel) data.trust_level = editTrustLevel;
		if (editManager) data.manager = editManager;
		if (editWorkers) data.workers = editWorkers.split(",").map((w) => w.trim()).filter(Boolean);

		try {
			await updateAgent(editingAgent.name, data);
			editingAgent = null;
			await refresh();
		} catch (e: any) {
			error = e.message || "Failed to update agent";
		}
	}

	async function handleDelete(name: string) {
		if (!confirm(`Delete agent "${name}"? This cannot be undone.`)) return;
		error = "";
		try {
			await deleteAgent(name);
			await refresh();
		} catch (e: any) {
			error = e.message || "Failed to delete agent";
		}
	}

	async function handleStart(name: string) {
		error = "";
		try {
			await startAgent(name);
			await refresh();
		} catch (e: any) {
			error = e.message || "Failed to start agent";
		}
	}

	async function handleStop(name: string) {
		error = "";
		try {
			await stopAgent(name);
			await refresh();
		} catch (e: any) {
			error = e.message || "Failed to stop agent";
		}
	}
</script>

<div class="mx-auto max-w-6xl p-6">
	<div class="mb-6 flex items-center justify-between">
		<div>
			<h1 class="text-2xl font-bold text-zinc-100">Agent Management</h1>
			<p class="mt-1 text-sm text-zinc-400">Create, configure, and manage agents</p>
		</div>
		<div class="flex gap-2">
			<a href="{base}/chat">
				<Button variant="ghost" size="sm" class="text-zinc-400">Back to Chat</Button>
			</a>
			<Button size="sm" onclick={() => (showCreate = true)}>New Agent</Button>
		</div>
	</div>

	{#if error}
		<div class="mb-4 rounded-md border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300">
			{error}
		</div>
	{/if}

	<!-- Tabs -->
	<div class="mb-4 flex gap-1 border-b border-zinc-800">
		<button
			class="px-4 py-2 text-sm font-medium transition-colors {activeTab === 'list'
				? 'border-b-2 border-zinc-100 text-zinc-100'
				: 'text-zinc-400 hover:text-zinc-200'}"
			onclick={() => (activeTab = "list")}
		>
			Agents
		</button>
		<button
			class="px-4 py-2 text-sm font-medium transition-colors {activeTab === 'hierarchy'
				? 'border-b-2 border-zinc-100 text-zinc-100'
				: 'text-zinc-400 hover:text-zinc-200'}"
			onclick={() => (activeTab = "hierarchy")}
		>
			Hierarchy
		</button>
	</div>

	{#if loading}
		<div class="py-12 text-center text-zinc-500">Loading agents...</div>
	{:else if activeTab === "list"}
		<!-- Agent list -->
		{#if agents.length === 0}
			<div class="py-12 text-center text-zinc-500">
				<p>No agents configured.</p>
				<p class="mt-2 text-sm">Create your first agent to get started.</p>
			</div>
		{:else}
			<div class="overflow-hidden rounded-lg border border-zinc-800">
				<table class="w-full text-sm">
					<thead class="bg-zinc-900/50">
						<tr class="text-left text-xs font-medium uppercase tracking-wider text-zinc-400">
							<th class="px-4 py-3">Name</th>
							<th class="px-4 py-3">Provider / Model</th>
							<th class="px-4 py-3">Type</th>
							<th class="px-4 py-3">Trust</th>
							<th class="px-4 py-3">Status</th>
							<th class="px-4 py-3 text-right">Actions</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-zinc-800">
						{#each agents as agent}
							<tr class="hover:bg-zinc-900/30">
								<td class="px-4 py-3">
									<div class="flex items-center gap-2">
										<div
											class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-zinc-700 text-xs font-medium text-zinc-300"
										>
											{agent.name.charAt(0).toUpperCase()}
										</div>
										<span class="font-medium text-zinc-200">{agent.name}</span>
									</div>
								</td>
								<td class="px-4 py-3 text-zinc-400">
									{agent.provider || "-"} / {agent.model || "-"}
								</td>
								<td class="px-4 py-3">
									<span
										class="rounded-full px-2 py-0.5 text-xs {agent.agent_type === 'management'
											? 'bg-purple-900/50 text-purple-300'
											: 'bg-zinc-800 text-zinc-400'}"
									>
										{agent.agent_type}
									</span>
								</td>
								<td class="px-4 py-3">
									<span
										class="rounded-full px-2 py-0.5 text-xs {agent.trust_level === 'privileged'
											? 'bg-amber-900/50 text-amber-300'
											: 'bg-zinc-800 text-zinc-400'}"
									>
										{agent.trust_level}
									</span>
								</td>
								<td class="px-4 py-3">
									<span
										class="inline-flex items-center gap-1.5 text-xs {agent.status === 'running'
											? 'text-emerald-400'
											: agent.status === 'stopped'
												? 'text-zinc-500'
												: 'text-zinc-400'}"
									>
										<span
											class="h-1.5 w-1.5 rounded-full {agent.status === 'running'
												? 'bg-emerald-500'
												: agent.status === 'stopped'
													? 'bg-zinc-600'
													: 'bg-zinc-600'}"
										></span>
										{agent.status}
									</span>
								</td>
								<td class="px-4 py-3 text-right">
									<div class="flex items-center justify-end gap-1">
										<button
											class="rounded px-2 py-1 text-xs text-emerald-400 hover:bg-emerald-950/50"
											onclick={() => handleStart(agent.name)}
										>
											Start
										</button>
										<button
											class="rounded px-2 py-1 text-xs text-amber-400 hover:bg-amber-950/50"
											onclick={() => handleStop(agent.name)}
										>
											Stop
										</button>
										<button
											class="rounded px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-800"
											onclick={() => openEdit(agent)}
										>
											Edit
										</button>
										<button
											class="rounded px-2 py-1 text-xs text-red-400 hover:bg-red-950/50"
											onclick={() => handleDelete(agent.name)}
										>
											Delete
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{:else}
		<!-- Hierarchy view -->
		{#if hierarchy.length === 0}
			<div class="py-12 text-center text-zinc-500">No hierarchy configured.</div>
		{:else}
			<div class="space-y-2">
				{#each hierarchy as node}
					{@render hierarchyNode(node, 0)}
				{/each}
			</div>
		{/if}
	{/if}

	<!-- Create dialog -->
	{#if showCreate}
		<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
			<div class="w-full max-w-lg rounded-lg border border-zinc-700 bg-zinc-900 p-6 shadow-xl">
				<h2 class="mb-4 text-lg font-semibold text-zinc-100">Create New Agent</h2>

				<div class="space-y-3">
					<div>
						<label for="agent-name" class="mb-1 block text-xs font-medium text-zinc-400">Name</label>
						<input
							id="agent-name"
							type="text"
							bind:value={newName}
							placeholder="my-agent"
							class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
						/>
					</div>

					<div class="grid grid-cols-2 gap-3">
						<div>
							<label for="agent-provider" class="mb-1 block text-xs font-medium text-zinc-400">Provider</label>
							<input
								id="agent-provider"
								type="text"
								bind:value={newProvider}
								placeholder="claude"
								class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
							/>
						</div>
						<div>
							<label for="agent-model" class="mb-1 block text-xs font-medium text-zinc-400">Model</label>
							<input
								id="agent-model"
								type="text"
								bind:value={newModel}
								placeholder="claude-sonnet-4-20250514"
								class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
							/>
						</div>
					</div>

					<div class="grid grid-cols-2 gap-3">
						<div>
							<label for="agent-type" class="mb-1 block text-xs font-medium text-zinc-400">Agent Type</label>
							<select
								id="agent-type"
								bind:value={newAgentType}
								class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-zinc-500 focus:outline-none"
							>
								<option value="worker">Worker</option>
								<option value="management">Management</option>
							</select>
						</div>
						<div>
							<label for="agent-trust" class="mb-1 block text-xs font-medium text-zinc-400">Trust Level</label>
							<select
								id="agent-trust"
								bind:value={newTrustLevel}
								class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-zinc-500 focus:outline-none"
							>
								<option value="restricted">Restricted</option>
								<option value="privileged">Privileged</option>
							</select>
						</div>
					</div>

					<div>
						<label class="flex items-center gap-2 text-sm text-zinc-300">
							<input type="checkbox" bind:checked={newLinuxUser} class="rounded" />
							Dedicated Linux user
						</label>
						{#if newLinuxUser}
							<input
								type="text"
								bind:value={newLinuxUserName}
								placeholder="botwerk-agentname"
								class="mt-2 w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
							/>
						{/if}
					</div>

					{#if templates.length > 0}
						<div>
							<label for="agent-template" class="mb-1 block text-xs font-medium text-zinc-400">Permission Template</label>
							<select
								id="agent-template"
								bind:value={newTemplate}
								class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-zinc-500 focus:outline-none"
							>
								<option value="">None</option>
								{#each templates as tmpl}
									<option value={tmpl.name}>{tmpl.name} - {tmpl.description}</option>
								{/each}
							</select>
						</div>
					{/if}
				</div>

				<div class="mt-5 flex justify-end gap-2">
					<Button
						variant="ghost"
						size="sm"
						class="text-zinc-400"
						onclick={() => {
							showCreate = false;
							resetCreateForm();
						}}
					>
						Cancel
					</Button>
					<Button size="sm" onclick={handleCreate} disabled={!newName}>Create</Button>
				</div>
			</div>
		</div>
	{/if}

	<!-- Edit dialog -->
	{#if editingAgent}
		<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
			<div class="w-full max-w-lg rounded-lg border border-zinc-700 bg-zinc-900 p-6 shadow-xl">
				<h2 class="mb-4 text-lg font-semibold text-zinc-100">
					Edit: {editingAgent.name}
				</h2>

				<div class="space-y-3">
					<div class="grid grid-cols-2 gap-3">
						<div>
							<label for="edit-provider" class="mb-1 block text-xs font-medium text-zinc-400">Provider</label>
							<input
								id="edit-provider"
								type="text"
								bind:value={editProvider}
								class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-zinc-500 focus:outline-none"
							/>
						</div>
						<div>
							<label for="edit-model" class="mb-1 block text-xs font-medium text-zinc-400">Model</label>
							<input
								id="edit-model"
								type="text"
								bind:value={editModel}
								class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-zinc-500 focus:outline-none"
							/>
						</div>
					</div>

					<div class="grid grid-cols-2 gap-3">
						<div>
							<label for="edit-type" class="mb-1 block text-xs font-medium text-zinc-400">Agent Type</label>
							<select
								id="edit-type"
								bind:value={editAgentType}
								class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-zinc-500 focus:outline-none"
							>
								<option value="worker">Worker</option>
								<option value="management">Management</option>
							</select>
						</div>
						<div>
							<label for="edit-trust" class="mb-1 block text-xs font-medium text-zinc-400">Trust Level</label>
							<select
								id="edit-trust"
								bind:value={editTrustLevel}
								class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-zinc-500 focus:outline-none"
							>
								<option value="restricted">Restricted</option>
								<option value="privileged">Privileged</option>
							</select>
						</div>
					</div>

					<div>
						<label for="edit-manager" class="mb-1 block text-xs font-medium text-zinc-400">Manager</label>
						<input
							id="edit-manager"
							type="text"
							bind:value={editManager}
							placeholder="Agent name"
							class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
						/>
					</div>

					<div>
						<label for="edit-workers" class="mb-1 block text-xs font-medium text-zinc-400">Workers (comma-separated)</label>
						<input
							id="edit-workers"
							type="text"
							bind:value={editWorkers}
							placeholder="agent1, agent2"
							class="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
						/>
					</div>
				</div>

				<div class="mt-5 flex justify-end gap-2">
					<Button
						variant="ghost"
						size="sm"
						class="text-zinc-400"
						onclick={() => (editingAgent = null)}
					>
						Cancel
					</Button>
					<Button size="sm" onclick={handleUpdate}>Save</Button>
				</div>
			</div>
		</div>
	{/if}
</div>

{#snippet hierarchyNode(node: AgentHierarchyNode, depth: number)}
	<div style="margin-left: {depth * 24}px">
		<div
			class="flex items-center gap-2 rounded-md border border-zinc-800 px-3 py-2 hover:bg-zinc-900/50"
		>
			{#if depth > 0}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="14"
					height="14"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="text-zinc-600"
				>
					<polyline points="9 18 15 12 9 6" />
				</svg>
			{/if}
			<div
				class="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-zinc-700 text-xs font-medium text-zinc-300"
			>
				{node.name.charAt(0).toUpperCase()}
			</div>
			<span class="text-sm font-medium text-zinc-200">{node.name}</span>
			<span
				class="rounded-full px-2 py-0.5 text-xs {node.agent_type === 'management'
					? 'bg-purple-900/50 text-purple-300'
					: 'bg-zinc-800 text-zinc-400'}"
			>
				{node.agent_type}
			</span>
		</div>
		{#if node.workers.length > 0}
			{#each node.workers as child}
				{@render hierarchyNode(child, depth + 1)}
			{/each}
		{/if}
	</div>
{/snippet}
