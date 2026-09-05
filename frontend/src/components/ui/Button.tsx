"use client";

import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "outline";
type Size = "sm" | "md" | "lg" | "icon";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-white hover:bg-accent/90 shadow-sm",
  secondary: "bg-elevated text-ink border border-line hover:border-strongline hover:bg-elevated/70",
  outline: "border border-line text-muted hover:text-ink hover:border-strongline",
  ghost: "text-muted hover:text-ink hover:bg-elevated",
  danger: "bg-down text-white hover:bg-down/90",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  lg: "h-11 px-6 text-sm gap-2",
  icon: "h-8 w-8",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "secondary", size = "md", loading, disabled, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      // A loading button stays labelled and focusable but refuses a second
      // click, so a slow scan cannot be started twice by an impatient double-tap.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center rounded-md font-medium",
        "transition-colors duration-150 whitespace-nowrap",
        "disabled:opacity-50 disabled:pointer-events-none",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
      {children}
    </button>
  );
});
