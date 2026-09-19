import type { Metadata, Viewport } from "next";

import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Intelligence Lab — NSE equity research",
    template: "%s · Intelligence Lab",
  },
  description:
    "Multi-timeframe stock scanning, walk-forward backtests, forward testing and " +
    "adaptive learning for NSE cash equities.",
  // Declared explicitly. With no icon the browser requests /favicon.ico on
  // every page and logs a 404 - two of them, with the apple-touch variant.
  // app/icon.svg is picked up by Next's file convention; naming it here also
  // stops the legacy .ico probe.
  icons: { icon: "/icon.svg", shortcut: "/icon.svg", apple: "/icon.svg" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#10131a" },
    { media: "(prefers-color-scheme: light)", color: "#f7f9fb" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href={
            "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&" +
            "family=JetBrains+Mono:wght@400;500;600&display=swap"
          }
        />
      </head>
      <body>
        <Providers>
          {/* Keyboard users land here first and can jump past the nav. */}
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3
              focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2
              focus:text-sm focus:text-white"
          >
            Skip to content
          </a>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <Header />
              <main id="main" className="min-w-0 flex-1">
                {children}
              </main>
              <footer className="min-w-0 border-t border-line px-4 py-3 text-2xs
                text-faint sm:px-6">
                <p className="break-words">
                  Free plan: first load can take up to a minute while the server wakes.
                  Research output only — this places no orders.
                </p>
              </footer>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
