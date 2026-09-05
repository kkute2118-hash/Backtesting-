"use client";

import { Check, CircleDashed, X } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader } from "@/components/ui/Card";
import { Note } from "@/components/ui/Misc";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { StrategyConditions } from "@/types/api";

/**
 * Why this stock did or did not qualify, rule by rule.
 *
 * ANDing these conditions reproduces the scanner's verdict exactly, so this is
 * the actual reason rather than a narrative written after the fact. For a rule
 * that fails on a continuous quantity the distance to its threshold is shown;
 * a structural rule ("inside yesterday's range") either holds or does not, and
 * says so instead of inventing a percentage.
 */
export function ConditionMatrix({ strategies }: { strategies: StrategyConditions[] }) {
  return (
    <Card>
      <CardHeader
        title="Strategy conditions"
        description="Every rule of every strategy, evaluated on the latest completed bar."
      />
      <div className="divide-y divide-line">
        {strategies.map((entry) => (
          <section key={entry.strategy} className="p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h3 className="text-xs font-semibold text-ink">{entry.label}</h3>
                {entry.signal ? (
                  <Badge tone="up" icon={<Check className="h-2.5 w-2.5" />}>All rules pass</Badge>
                ) : (
                  <Badge tone="neutral">
                    {entry.total - entry.passed} rule
                    {entry.total - entry.passed === 1 ? "" : "s"} failing
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="tabular text-2xs text-muted">
                  {entry.passed}/{entry.total}
                </span>
                <span className="h-1.5 w-24 overflow-hidden rounded-full bg-elevated" aria-hidden>
                  <span
                    className={cn("block h-full rounded-full",
                      entry.signal ? "bg-up" : "bg-accent")}
                    style={{ width: `${(entry.passed / Math.max(1, entry.total)) * 100}%` }}
                  />
                </span>
              </div>
            </div>

            <ul className="grid gap-1.5 sm:grid-cols-2">
              {entry.conditions.map((condition) => (
                <li
                  key={condition.name}
                  className={cn(
                    "flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-xs",
                    condition.passed
                      ? "border-up/25 bg-up-soft/30 text-ink"
                      : "border-line bg-elevated text-muted",
                  )}
                >
                  <span className="mt-0.5 shrink-0" aria-hidden>
                    {condition.passed ? (
                      <Check className="h-3 w-3 text-up" />
                    ) : condition.distance_pct !== null ? (
                      <CircleDashed className="h-3 w-3 text-warn" />
                    ) : (
                      <X className="h-3 w-3 text-faint" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block">{condition.name}</span>
                    {!condition.passed && condition.distance_pct !== null ? (
                      <span className="mt-0.5 block text-2xs text-warn">
                        {pct(condition.distance_pct, 1)} away from the threshold
                      </span>
                    ) : null}
                  </span>
                  <span className="sr-only">{condition.passed ? "passes" : "fails"}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <div className="border-t border-line px-4 py-2.5">
        <Note>
          A stock qualifies only when every rule of a strategy passes. One attractive condition is
          never enough, and the score does not override a failing rule.
        </Note>
      </div>
    </Card>
  );
}
