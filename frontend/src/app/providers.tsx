"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useEffect, useState, type ReactNode } from "react";
import { Toaster } from "sonner";

import { ApiError, pingHealth } from "@/lib/api";

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
              return failureCount < 2;
            },
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
