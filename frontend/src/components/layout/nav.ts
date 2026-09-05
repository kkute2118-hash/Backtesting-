import {
  Activity, BarChart3, Brain, Database, Eye, LayoutDashboard, Radar,
  Settings, Target, TestTube2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  description: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/**
 * The information architecture.
 *
 * The Streamlit build had fifteen flat tabs in one row, which gave a research
 * study the same visual weight as the scanner. These four groups follow the
 * actual workflow — find something, track it, prove it, feed it — so the daily
 * path (Dashboard → Scanner → a stock) is the shortest one.
 */
export const NAV: NavGroup[] = [
  {
    label: "Research",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard,
        description: "Market, data health and the state of the book" },
      { href: "/scanner", label: "Scanner", icon: Target,
        description: "Run S1-S4 across a universe" },
      { href: "/radar", label: "Early Warning", icon: Radar,
        description: "Setups forming before they trigger" },
      { href: "/watchlist", label: "Watchlist", icon: Eye,
        description: "Stocks you are tracking" },
    ],
  },
  {
    label: "Positions",
    items: [
      { href: "/forward", label: "Forward Tests", icon: Activity,
        description: "Live P/L on recorded signals" },
    ],
  },
  {
    label: "Evidence",
    items: [
      { href: "/backtest", label: "Backtest", icon: BarChart3,
        description: "Walk-forward replay and studies" },
      { href: "/learning", label: "Learning", icon: Brain,
        description: "What historically worked, and how sure we are" },
      { href: "/research", label: "Research Lab", icon: TestTube2,
        description: "Custom rules, fundamentals, SMC, AI panels" },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/data", label: "Data Manager", icon: Database,
        description: "Sync, diagnostics and database backup" },
      { href: "/settings", label: "Settings", icon: Settings,
        description: "Configuration status and defaults" },
    ],
  },
];

export const ALL_NAV_ITEMS = NAV.flatMap((group) => group.items);

export function activeItem(pathname: string): NavItem | undefined {
  const exact = ALL_NAV_ITEMS.find((item) => item.href === pathname);
  if (exact) return exact;
  return ALL_NAV_ITEMS
    .filter((item) => item.href !== "/" && pathname.startsWith(item.href))
    .sort((a, b) => b.href.length - a.href.length)[0];
}
