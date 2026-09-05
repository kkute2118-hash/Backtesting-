"use client";

import { RotateCcw, SlidersHorizontal, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { BoundInput, CheckboxGroup, RangeField } from "@/components/ui/Inputs";
import { cn } from "@/lib/utils";
import type { ResultFilters } from "@/hooks/queries";

export const EMPTY_FILTERS: ResultFilters = {
  search: "",
  strategies: [],
  safety_status: [],
  min_score: null,
  min_rsi: null,
  max_rsi: null,
  min_relvol: null,
  min_price: null,
  max_price: null,
  min_win_probability: null,
  min_safety: null,
  min_htf: null,
  min_footprint: null,
};

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2.5 border-b border-line pb-4 last:border-0 last:pb-0">
      <h3 className="text-2xs font-semibold uppercase tracking-wider text-faint">{title}</h3>
      {children}
    </section>
  );
}

/**
 * Post-scan result filters.
 *
 * These never re-run the engine — they narrow a finished result set, which is
 * why they can be sliders. Grouping them by what the number *means* (price,
 * momentum, quality, risk) rather than listing thirty inputs in a column is
 * the difference between a screening tool and a form.
 */
function FilterFields({
  value,
  onChange,
  strategies,
}: {
  value: ResultFilters;
  onChange: (next: ResultFilters) => void;
  strategies: string[];
}) {
  function set<K extends keyof ResultFilters>(key: K, next: ResultFilters[K]) {
    onChange({ ...value, [key]: next });
  }

  return (
    <div className="space-y-4">
      <Group title="Signal quality">
        <RangeField
          label="Minimum score"
          value={value.min_score ?? 0}
          onChange={(next) => set("min_score", next === 0 ? null : next)}
          min={0}
          max={100}
          hint="The forward-test gate is 85. Below it a setup is research, not a candidate."
        />
        <BoundInput
          label="Minimum win probability %"
          value={value.min_win_probability ?? null}
          onChange={(next) => set("min_win_probability", next)}
        />
      </Group>

      <Group title="Strategy">
        {strategies.length > 0 ? (
          <CheckboxGroup
            options={strategies.map((strategy) => ({ value: strategy, label: strategy }))}
            selected={value.strategies ?? []}
            onChange={(next) => set("strategies", next)}
          />
        ) : (
          <p className="text-2xs text-faint">No strategies in this result set.</p>
        )}
      </Group>

      <Group title="Price">
        <div className="grid grid-cols-2 gap-2">
          <BoundInput label="Min ₹" value={value.min_price ?? null}
            onChange={(next) => set("min_price", next)} />
          <BoundInput label="Max ₹" value={value.max_price ?? null}
            onChange={(next) => set("max_price", next)} />
        </div>
      </Group>

      <Group title="Momentum">
        <div className="grid grid-cols-2 gap-2">
          <BoundInput label="Min RSI" value={value.min_rsi ?? null}
            onChange={(next) => set("min_rsi", next)} />
          <BoundInput label="Max RSI" value={value.max_rsi ?? null}
            onChange={(next) => set("max_rsi", next)} />
        </div>
      </Group>

      <Group title="Volume">
        <BoundInput
          label="Minimum relative volume"
          value={value.min_relvol ?? null}
          onChange={(next) => set("min_relvol", next)}
          step="0.1"
        />
      </Group>

      <Group title="Risk">
        <RangeField
          label="Minimum safety score"
          value={value.min_safety ?? 0}
          onChange={(next) => set("min_safety", next === 0 ? null : next)}
          min={0}
          max={100}
        />
        <CheckboxGroup
          options={[
            { value: "ELIGIBLE", label: "Eligible" },
            { value: "CAUTION", label: "Caution" },
            { value: "REJECT", label: "Reject" },
          ]}
          selected={value.safety_status ?? []}
          onChange={(next) => set("safety_status", next)}
        />
      </Group>

      <Group title="Score components">
        <div className="grid grid-cols-2 gap-2">
          <BoundInput label="Min HTF demand" value={value.min_htf ?? null}
            onChange={(next) => set("min_htf", next)} />
          <BoundInput label="Min footprint" value={value.min_footprint ?? null}
            onChange={(next) => set("min_footprint", next)} />
        </div>
      </Group>
    </div>
  );
}

export function activeFilterCount(filters: ResultFilters): number {
  let count = 0;
  for (const [key, value] of Object.entries(filters)) {
    if (["sort_by", "sort_dir", "offset", "limit", "search"].includes(key)) continue;
    if (value === null || value === undefined) continue;
    if (Array.isArray(value) ? value.length > 0 : true) count += 1;
  }
  return count;
}

/** Desktop: a sticky rail. Small screens: a sheet, so the table keeps the width. */
export function FilterPanel({
  value,
  onChange,
  onReset,
  strategies,
}: {
  value: ResultFilters;
  onChange: (next: ResultFilters) => void;
  onReset: () => void;
  strategies: string[];
}) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const count = activeFilterCount(value);

  return (
    <>
      <div className="lg:hidden">
        <Button size="sm" variant="secondary" onClick={() => setSheetOpen(true)}>
          <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
          Filters
          {count > 0 ? (
            <span className="ml-0.5 rounded-full bg-accent px-1.5 text-2xs text-white">
              {count}
            </span>
          ) : null}
        </Button>
      </div>

      <aside className="hidden w-64 shrink-0 lg:block">
        <div className="sticky top-20 rounded-card border border-line bg-surface shadow-card">
          <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
            <h2 className="flex items-center gap-1.5 text-xs font-semibold text-ink">
              <SlidersHorizontal className="h-3.5 w-3.5 text-accent" aria-hidden />
              Filters
              {count > 0 ? (
                <span className="rounded-full bg-accent px-1.5 text-2xs text-white">{count}</span>
              ) : null}
            </h2>
            <button
              type="button"
              onClick={onReset}
              disabled={count === 0}
              className="flex items-center gap-1 text-2xs text-faint hover:text-ink
                disabled:opacity-40"
            >
              <RotateCcw className="h-3 w-3" aria-hidden />
              Reset
            </button>
          </div>
          <div className="max-h-[calc(100vh-11rem)] overflow-y-auto scroll-thin p-3.5">
            <FilterFields value={value} onChange={onChange} strategies={strategies} />
          </div>
        </div>
      </aside>

      {sheetOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/60 animate-fade-in"
            onClick={() => setSheetOpen(false)} aria-hidden />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Filters"
            className={cn("absolute bottom-0 left-0 right-0 max-h-[85vh] rounded-t-2xl border-t",
              "border-line bg-surface shadow-pop")}
          >
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <h2 className="text-sm font-semibold text-ink">Filters</h2>
              <div className="flex items-center gap-1">
                <Button size="sm" variant="ghost" onClick={onReset} disabled={count === 0}>
                  Reset
                </Button>
                <button type="button" onClick={() => setSheetOpen(false)}
                  aria-label="Close filters" className="rounded p-1 text-faint hover:text-ink">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="max-h-[calc(85vh-7rem)] overflow-y-auto scroll-thin p-4">
              <FilterFields value={value} onChange={onChange} strategies={strategies} />
            </div>
            <div className="border-t border-line p-3">
              <Button variant="primary" className="w-full" onClick={() => setSheetOpen(false)}>
                Show results
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
