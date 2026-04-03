<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { auth } from "$lib/stores.js";
	import { login, setup, getMe } from "$lib/api.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import {
		Card,
		CardHeader,
		CardTitle,
		CardDescription,
		CardContent,
		CardFooter,
	} from "$lib/components/ui/card/index.js";

	let username = $state("");
	let password = $state("");
	let error = $state("");
	let isSetup = $state(false);
	let submitting = $state(false);

	// Check if setup is needed (no users exist)
	$effect(() => {
		getMe()
			.then((user) => {
				auth.user = user;
				goto(`${base}/chat`);
			})
			.catch((err: Error) => {
				if (err.message.includes("setup")) {
					isSetup = true;
				}
			});
	});

	async function handleSubmit(e: Event) {
		e.preventDefault();
		error = "";
		submitting = true;

		try {
			const action = isSetup ? setup : login;
			const user = await action(username, password);
			auth.user = user;
			goto(`${base}/chat`);
		} catch (err) {
			error = err instanceof Error ? err.message : "An error occurred";
		} finally {
			submitting = false;
		}
	}
</script>

<div class="flex min-h-screen items-center justify-center p-4">
	<Card class="w-full max-w-sm">
		<CardHeader class="text-center">
			<CardTitle class="text-2xl">
				{isSetup ? "Create Admin Account" : "Sign In"}
			</CardTitle>
			<CardDescription>
				{isSetup
					? "Set up your first admin account to get started."
					: "Enter your credentials to access Botwerk."}
			</CardDescription>
		</CardHeader>
		<form onsubmit={handleSubmit}>
			<CardContent class="space-y-4">
				{#if error}
					<div class="rounded-md bg-red-900/50 border border-red-800 p-3 text-sm text-red-200">
						{error}
					</div>
				{/if}
				<div class="space-y-2">
					<Label for="username">Username</Label>
					<Input
						id="username"
						type="text"
						placeholder="admin"
						autocomplete="username"
						bind:value={username}
						required
					/>
				</div>
				<div class="space-y-2">
					<Label for="password">Password</Label>
					<Input
						id="password"
						type="password"
						placeholder="••••••••"
						autocomplete={isSetup ? "new-password" : "current-password"}
						bind:value={password}
						required
					/>
				</div>
			</CardContent>
			<CardFooter>
				<Button type="submit" class="w-full" disabled={submitting}>
					{#if submitting}
						{isSetup ? "Creating..." : "Signing in..."}
					{:else}
						{isSetup ? "Create Account" : "Sign In"}
					{/if}
				</Button>
			</CardFooter>
		</form>
	</Card>
</div>
