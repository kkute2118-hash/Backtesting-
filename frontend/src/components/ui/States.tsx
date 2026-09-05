"use client";

import { AlertTriangle, Inbox, Loader2, RefreshCw, Settings2, WifiOff } from "lucide-react";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

import { Button } from "./Button";

/** A shimmering placeholder shaped like the content it stands in for. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("relative overflow-hidden rounded bg-elevated", className)}
      aria-hidden
    >
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r
        from-transparent via-white/5 to-transparent" />
    </div>
  );
}

export function SkeletonTable({ rows = 6, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-2 p-4" role="status" aria-label="Loading results">
      <Skeleton className="h-8 w-full" />
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex gap-2">
          {Array.from({ length: cols }).map((_, colIndex) => (
            <Skeleton
              key={colIndex}
              className={cn("h-7", colIndex === 0 ? "w-28" : "flex-1")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" role="status" aria-label="Loading">
      {Array.from({ length: count }).map((_, index) => (
        <Skeleton key={index} className="h-24 w-full rounded-card" />
      ))}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted"
      role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label ?? "Loading…"}
    </div>
  );
}

/**
 * A failure the user can act on.
 *
 * The backend distinguishes "you have not configured Dhan" from "Dhan is
 * down", and those need different words and different buttons — telling
 * someone to retry a request that can never succeed until they add a key is
 * worse than useless.
 */
export function ErrorState({
  error,
  onRetry,
  compact: isCompact,
}: {
  error: unknown;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const isNetwork = apiError?.code === "network_error";
  const isConfig = apiError?.isNotConfigured ?? false;

  const Icon = isNetwork ? WifiOff : isConfig ? Settings2 : AlertTriangle;
  const tone = isConfig ? "text-warn" : "text-down";
  const title = isNetwork
    ? "Cannot reach the server"
    : isConfig
      ? "Not configured yet"
      : "Something went wrong";
  const message =
    apiError?.message ??
    (error instanceof Error ? error.message : "An unexpected error occurred.");

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center gap-3 rounded-card border border-line bg-surface text-center",
        isCompact ? "px-4 py-6" : "px-6 py-12",
      )}
    >
      <Icon className={cn("h-6 w-6", tone)} aria-hidden />
      <div className="max-w-md space-y-1">
        <p className="text-sm font-semibold text-ink">{title}</p>
        <p className="text-xs leading-relaxed text-muted">{message}</p>
      </div>
      {onRetry && !isConfig ? (
        <Button size="sm" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function EmptyState({
  title,
  message,
  action,
  icon,
}: {
  title: string;
  message?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <div className="text-faint" aria-hidden>{icon ?? <Inbox className="h-6 w-6" />}</div>
      <div className="max-w-md space-y-1">
        <p className="text-sm font-semibold text-ink">{title}</p>
        {message ? <p className="text-xs leading-relaxed text-muted">{message}</p> : null}
      </div>
      {action}
    </div>
  );
}

/** A determinate progress bar for a job whose progress the backend reports. */
export function Progress({
  value,
  label,
  className,
}: {
  value: number;
  label?: string;
  className?: string;
}) {
  const percent = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className={cn("space-y-1.5", className)}>
      {label ? (
        <div className="flex items-center justify-between text-xs text-muted">
          <span>{label}</span>
          <span className="tabular">{percent}%</span>
        </div>
      ) : null}
      <div
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "Progress"}
        className="h-1.5 w-full overflow-hidden rounded-full bg-elevated"
      >
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-300 ease-out"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
