"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Kept in the console for a developer; the page itself shows no stack trace.
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 px-5 py-24 text-center">
      <AlertTriangle className="h-7 w-7 text-down" aria-hidden />
      <h1 className="text-lg font-semibold text-ink">This page could not be displayed</h1>
      <p className="text-xs leading-relaxed text-muted">
        Something went wrong while rendering. Retrying often clears it; if it
        persists, check that the analysis server is reachable.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-1 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white
          hover:bg-accent/90"
      >
        Try again
      </button>
    </div>
  );
}
