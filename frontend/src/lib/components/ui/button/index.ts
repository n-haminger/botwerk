import { tv, type VariantProps } from "tailwind-variants";
import type { Snippet } from "svelte";
import type { HTMLButtonAttributes } from "svelte/elements";

export const buttonVariants = tv({
	base: "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-300 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
	variants: {
		variant: {
			default: "bg-zinc-50 text-zinc-900 shadow hover:bg-zinc-50/90",
			destructive: "bg-red-900 text-zinc-50 shadow-sm hover:bg-red-900/90",
			outline: "border border-zinc-800 bg-transparent shadow-sm hover:bg-zinc-800 hover:text-zinc-50",
			secondary: "bg-zinc-800 text-zinc-50 shadow-sm hover:bg-zinc-800/80",
			ghost: "hover:bg-zinc-800 hover:text-zinc-50",
			link: "text-zinc-50 underline-offset-4 hover:underline",
		},
		size: {
			default: "h-9 px-4 py-2",
			sm: "h-8 rounded-md px-3 text-xs",
			lg: "h-10 rounded-md px-8",
			icon: "h-9 w-9",
		},
	},
	defaultVariants: {
		variant: "default",
		size: "default",
	},
});

export type ButtonVariant = VariantProps<typeof buttonVariants>["variant"];
export type ButtonSize = VariantProps<typeof buttonVariants>["size"];

export interface ButtonProps extends HTMLButtonAttributes {
	variant?: ButtonVariant;
	size?: ButtonSize;
	children?: Snippet;
	class?: string;
}

export { default as Button } from "./Button.svelte";
