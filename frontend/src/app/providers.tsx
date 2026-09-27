"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useEffect, useState, type ReactNode } from "react";
import { Toaster } from "sonner";

import { ApiError, pingHealth } from "@/lib/api";

/**
 * True when the failure came from the hosting layer rather than the API.
 *
 * Status 0 is a request that never got an answer (a sleeping or restarting
 * instance, whose proxy page carries no CORS headers). A 502-504 WITHOUT the
 * backend's error envelope - code "error" - is Render's own gateway page.
 */
function isServerAbsent(error: ApiError): boolean {
  if (error.status === 0) return true;
  return [502, 503, 504].includes(error.status) && error.code === "error";
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            // Retrying a 4xx just delays the error the user needs to read.
            // A network blip or a 5xx is worth one more attempt.
            retry: (failureCount, error) => {
              if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
                return false;
              }
              // The server itself is not there yet: Render is waking it from
              // sleep, or restarting it, which takes 40-60 seconds. The old two
              // quick retries gave up after ~3s and showed "cannot reach" for a
              // server that answered moments later. Wait it out instead. A 5xx
              // in the backend's own envelope (a Dhan refusal, a missing
              // setting) is a real answer and keeps the short budget.
              if (error instanceof ApiError && isServerAbsent(error)) {
                return failureCount < 6;
              }
              return failureCount < 2;
            },
            // 1s, 2s, 4s, 8s, 15s, 15s: about 45s in all, the span of a wake-up.
            retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 15_000),
          },
          mutations: { retry: false },
        },
      }),
  );

  // Wake the backend as early as possible. On Render's free plan a sleeping
  // instance takes up to a minute to answer its first request, and every page
  // would otherwise wait for a real query to trigger that. /health needs no
  // database, so it starts the boot without competing for it. Failures are
  // ignored on purpose - this is a nudge, not a dependency.
  useEffect(() => {
    void pingHealth();
  }, []);

  return (
    <QueryClientProvider client={client}>
      <ThemeProvider
        attribute="class"
        defaultTheme="dark"
        enableSystem={false}
        disableTransitionOnChange
      >
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            className: "!bg-surface !text-ink !border !border-line !text-xs",
          }}
        />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
