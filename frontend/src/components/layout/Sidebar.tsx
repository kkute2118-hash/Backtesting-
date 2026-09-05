"use client";

import { LineChart, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { cn } from "@/lib/utils";

import { NAV } from "./nav";

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  function isActive(href: string) {
    return href === "/" ? pathname === "/" : pathname.startsWith(href);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-line px-4">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/15
          text-accent" aria-hidden>
          <LineChart className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-tight tracking-tight">
            Intelligence Lab
          </p>
          <p className="truncate text-2xs text-faint">NSE equity research</p>
        </div>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto scroll-thin px-2.5 py-4"
        aria-label="Main navigation">
        {NAV.map((group) => (
          <div key={group.label}>
            <p className="px-2 pb-1.5 text-2xs font-semibold uppercase tracking-wider text-faint">
              {group.label}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = isActive(item.href);
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      title={item.description}
                      className={cn(
                        "group flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm",
                        "transition-colors duration-150",
                        active
                          ? "bg-accent-soft text-ink"
                          : "text-muted hover:bg-elevated hover:text-ink",
                      )}
                    >
                      <Icon
                        className={cn("h-4 w-4 shrink-0",
                          active ? "text-accent" : "text-faint group-hover:text-muted")}
                        aria-hidden
                      />
                      <span className="truncate">{item.label}</span>
                      {active ? (
                        <span className="ml-auto h-1 w-1 rounded-full bg-accent" aria-hidden />
                      ) : null}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-line px-4 py-3">
        <p className="text-2xs leading-relaxed text-faint">
          Research and decision support. It places no orders, and a score ranks
          setup quality rather than predicting an outcome.
        </p>
      </div>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 border-r border-line bg-surface lg:block">
      <div className="sticky top-0 h-screen">
        <SidebarContent />
      </div>
    </aside>
  );
}

/** The same navigation as a drawer on small screens. */
export function MobileSidebar({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div
        className="absolute inset-0 bg-black/60 animate-fade-in"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        className="absolute left-0 top-0 h-full w-64 border-r border-line bg-surface shadow-pop"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close navigation"
          className="absolute right-2 top-4 rounded p-1 text-faint hover:text-ink"
        >
          <X className="h-4 w-4" />
        </button>
        <SidebarContent onNavigate={onClose} />
      </div>
    </div>
  );
}
