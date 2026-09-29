"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";

import { ChartProvider } from "@/features/chart/ChartProvider";
import { ApiError } from "@/lib/api";

/**
 * True when the failure came from the hosting layer rather than the API.
 *
 * Status 0 is a request that never got an answer (a restarting API, whose
 * proxy page carries no CORS headers). A 502-504 WITHOUT the backend's error
 * envelope - code "error" - is the proxy's own error page.
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
              // The API is restarting (an update swaps its container in a few
              // seconds): a few more tries cover it. A 5xx in the backend's
              // own envelope (a Dhan refusal, a missing setting) is a real
              // answer and keeps the short budget.
              if (error instanceof ApiError && isServerAbsent(error)) {
                return failureCount < 3;
              }
              return failureCount < 2;
            },
            // 1s, 2s, 4s: about 7s in all. The server never sleeps.
            retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 4_000),
          },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <ThemeProvider
        attribute="class"
        defaultTheme="dark"
        enableSystem={false}
        disableTransitionOnChange
      >
        <ChartProvider>{children}</ChartProvider>
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
