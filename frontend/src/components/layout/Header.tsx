"use client";

import { Activity, Menu } from "lucide-react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { useState } from "react";

import { useOverview } from "@/hooks/queries";
import { date } from "@/lib/format";
import { cn } from "@/lib/utils";

import { CommandSearch } from "./CommandSearch";
import { MobileSidebar } from "./Sidebar";
import { ThemeToggle } from "./ThemeToggle";
import { activeItem } from "./nav";

/** Live market state, so the freshness of everything below is never ambiguous. */
function MarketPill() {
  const { data } = useOverview();
  const market = data?.market;
  if (!market) return null;

  return (
    <div className="hidden shrink-0 items-center gap-2 whitespace-nowrap rounded-md border
      border-line bg-elevated px-2.5 py-1 md:flex">
      <span
        className={cn("h-1.5 w-1.5 rounded-full",
          market.is_open ? "bg-up animate-pulse" : "bg-faint")}
        aria-hidden
      />
      <span className="text-2xs font-medium text-ink">
        NSE {market.is_open ? "open" : "closed"}
      </span>
      <span className="hidden text-2xs text-faint lg:inline">
        {market.is_open
          ? `until ${market.close_time} IST`
          : `last close ${date(market.last_completed_session)}`}
      </span>
    </div>
  );
}

/**
 * Market breadth: the gate S1, S2, S3 and S6 wait on. Shown on every page and
 * on phones, because it decides whether most strategies can trade at all.
 */
function BreadthPill() {
  const { data } = useOverview();
  const b = data?.market_breadth;
  if (!b?.ready || b.latest === null) return null;
  const open = b.gate_open;
  return (
    <Link
      href="/#market-breadth"
      title={`Market breadth ${b.latest.toFixed(2)} (needs ${b.threshold.toFixed(2)}): ` +
        `${open ? "open" : "waiting"} for ${b.gated_strategies.join(", ")}. ` +
        `Share of ${b.universe} stocks at a 50-day high, summed over ${b.window} sessions.`}
      data-testid="breadth-pill"
      className={cn("flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-1",
        open ? "border-up/40 bg-up-soft text-up" : "border-warn/40 bg-warn-soft text-warn")}
    >
      <Activity className="h-3.5 w-3.5" aria-hidden />
      <span className="text-2xs font-semibold tabular">{b.latest.toFixed(2)}</span>
      <span className="hidden text-2xs font-medium sm:inline">
        {open ? "breadth open" : `breadth · needs ${b.threshold.toFixed(2)}`}
      </span>
    </Link>
  );
}

/** Where you are, in one line. A run page is a child of the tool that made it. */
function breadcrumbs(pathname: string): Array<{ label: string; href?: string }> {
  if (pathname.startsWith("/stocks/")) {
    return [
      { label: "Stocks", href: "/scanner" },
      { label: decodeURIComponent(pathname.split("/")[2] ?? "").toUpperCase() },
    ];
  }
  if (pathname.startsWith("/scanner/runs/")) {
    return [{ label: "Scanner", href: "/scanner" }, { label: "Results" }];
  }
  const current = activeItem(pathname);
  return [{ label: current?.label ?? "Dashboard" }];
}


export function Header() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const pathname = usePathname();
  const crumbs = breadcrumbs(pathname);

  return (
    <>
      <header className="sticky top-0 z-40 flex h-14 shrink-0 items-center gap-3 border-b
        border-line bg-canvas/85 px-3 backdrop-blur-md sm:px-5">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation"
          className="rounded-md p-1.5 text-muted hover:bg-elevated hover:text-ink lg:hidden"
        >
          <Menu className="h-4.5 w-4.5" style={{ height: "1.125rem", width: "1.125rem" }} />
        </button>

        <nav aria-label="Breadcrumb" className="hidden min-w-0 sm:block">
          <ol className="flex items-center gap-1.5 text-sm">
            {crumbs.map((crumb, index) => (
              <li key={crumb.label} className="flex items-center gap-1.5">
                {index > 0 ? <span className="text-faint" aria-hidden>/</span> : null}
                {crumb.href && index < crumbs.length - 1 ? (
                  <Link href={crumb.href} className="text-muted hover:text-ink">
                    {crumb.label}
                  </Link>
                ) : (
                  <span className="truncate font-semibold text-ink">{crumb.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <BreadthPill />
          <MarketPill />
          <CommandSearch />
          <ThemeToggle />
        </div>
      </header>

      <MobileSidebar open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  );
}
