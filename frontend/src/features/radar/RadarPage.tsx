"use client";

import { Play, Radar } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { CheckboxGroup, Field, RangeField, Select } from "@/components/ui/Inputs";
import { Note, Stat, SymbolLink } from "@/components/ui/Misc";
import { ErrorState, SkeletonTable } from "@/components/ui/States";
import { JobProgress } from "@/features/scanner/JobProgress";
import { STRATEGY_OPTIONS, num as n, str } from "@/features/scanner/shared";
import { useJob, useRadarRuns, useRun, useStartRadar, useUniverses } from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { int, num, pct, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Row } from "@/types/api";

/**
 * The Early Warning Radar.
 *
 * The scanner is binary — a stock is invisible until the day every rule passes,
 * which is usually the day the move has already started. This answers the other
 * question: which stocks are close, which rule is blocking them, and how far
 * away it is. Setting "rules allowed to fail" to 0 reproduces the scanner's
 * qualified list exactly, which is the guarantee that this changes nothing
 * about qualification.
 */
export function RadarPage() {
  const [universes, setUniverses] = useState<string[]>(["Nifty 500"]);
  const [strategies, setStrategies] = useState<number[]>([1, 2, 3, 4]);
  const [maxMissing, setMaxMissing] = useState(2);
  const [minReadiness, setMinReadiness] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);

  const { data: universeOptions } = useUniverses();
  const { data: recentRuns } = useRadarRuns(6);
  const startRadar = useStartRadar();
  const { data: job } = useJob(runId);
  // A run opened from history has no live job, so results are fetched
  // whenever the run is not currently in flight.
  const run = useRun(runId, job?.status !== "running" && job?.status !== "queued");

  useEffect(() => {
    if (job?.status === "failed") toast.error(job.error ?? "The radar run failed.");
  }, [job?.status, job?.error]);

  // Open on the most recent successful run rather than an empty table — a radar
  // result stays useful for the rest of the session it was produced in.
  useEffect(() => {
    if (runId || !recentRuns) return;
    const latest = recentRuns.find((entry) => entry.status === "succeeded");
    if (latest) setRunId(latest.id);
  }, [recentRuns, runId]);

  async function start() {
    try {
      const started = await startRadar.mutateAsync({
        universes, strategies, max_missing: maxMissing, min_readiness: minReadiness,
      });
      setRunId(started.id);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  const rows = run.data?.rows ?? [];
  const stats = (run.data?.stats ?? {}) as Record<string, unknown>;
  const blockingRules = (stats.blocking_rules ?? []) as Row[];

  // early_warning_radar() returns these exact column names; they are display
  // strings from the engine, so the keys below must match it character for
  // character or the table renders blank cells.
  const columns: Column<Row>[] = [
    { key: "Ticker", header: "Symbol", sticky: true, width: "7.5rem",
      render: (row) => <SymbolLink symbol={str(row, "Ticker")} />,
      value: (row) => str(row, "Ticker") },
    { key: "Strategy", header: "Strategy",
      render: (row) => <Badge tone="accent">{str(row, "Strategy")}</Badge>,
      value: (row) => str(row, "Strategy") },
    { key: "State", header: "State", sortable: false,
      render: (row) => <span className="text-2xs">{str(row, "State") || "—"}</span>,
      value: (row) => str(row, "State") },
    { key: "Readiness", header: "Readiness", align: "right",
      render: (row) => {
        const value = n(row, "Readiness");
        if (value === null) return <span className="text-faint">—</span>;
        return (
          <span className="inline-flex items-center justify-end gap-2">
            <span className="tabular font-semibold">{num(value, 0)}</span>
            <span className="h-1 w-12 overflow-hidden rounded-full bg-elevated" aria-hidden>
              <span className="block h-full rounded-full bg-accent"
                style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
            </span>
          </span>
        );
      },
      value: (row) => n(row, "Readiness"),
      description: "55% proximity to trigger + 35% volatility compression + regime adjustment." },
    { key: "Rules Passing", header: "Rules passing", align: "right", sortable: false,
      render: (row) => str(row, "Rules Passing") || "—",
      value: (row) => str(row, "Rules Passing") },
    { key: "Missing Rules", header: "Blocking rules", sortable: false,
      render: (row) => {
        const missing = str(row, "Missing Rules");
        return !missing || missing === "\u2014"
          ? <span className="text-2xs text-up">None</span>
          : <span className="text-2xs text-warn" title={missing}>{missing}</span>;
      },
      value: (row) => str(row, "Missing Rules") },
    { key: "Worst Gap %", header: "Worst gap", align: "right",
      render: (row) => pct(n(row, "Worst Gap %"), 1),
      value: (row) => n(row, "Worst Gap %"),
      description: "How far the furthest continuously-closing rule still has to move." },
    { key: "Proximity", header: "Proximity", align: "right",
      render: (row) => num(n(row, "Proximity"), 0), value: (row) => n(row, "Proximity") },
    { key: "Compression", header: "Compression", align: "right",
      render: (row) => num(n(row, "Compression"), 0), value: (row) => n(row, "Compression"),
      description: "Range percentile, inside bars, NR7 and volume dry-up combined." },
    { key: "Close", header: "Close", align: "right",
      render: (row) => num(n(row, "Close"), 2), value: (row) => n(row, "Close") },
    { key: "From 52w High %", header: "From 52w high", align: "right",
      render: (row) => pct(n(row, "From 52w High %"), 1),
      value: (row) => n(row, "From 52w High %") },
    { key: "Squeeze %ile", header: "Squeeze %ile", align: "right", optional: true,
      render: (row) => num(n(row, "Squeeze %ile"), 1), value: (row) => n(row, "Squeeze %ile") },
    { key: "Range Ratio", header: "Range ratio", align: "right", optional: true,
      render: (row) => num(n(row, "Range Ratio"), 2), value: (row) => n(row, "Range Ratio") },
    { key: "Vol Dry-Up", header: "Vol dry-up", align: "right", optional: true,
      render: (row) => num(n(row, "Vol Dry-Up"), 2), value: (row) => n(row, "Vol Dry-Up") },
    { key: "Inside Bars", header: "Inside bars", align: "right", optional: true,
      render: (row) => int(n(row, "Inside Bars")), value: (row) => n(row, "Inside Bars") },
    { key: "NR7", header: "NR7", optional: true, sortable: false,
      render: (row) => (row.NR7 ? <Badge tone="accent">NR7</Badge> : "—"),
      value: (row) => String(row.NR7 ?? "") },
    { key: "Dist to EMA20 %", header: "vs EMA20", align: "right", optional: true,
      render: (row) => pct(n(row, "Dist to EMA20 %"), 2),
      value: (row) => n(row, "Dist to EMA20 %") },
    { key: "ATR %", header: "ATR %", align: "right", optional: true,
      render: (row) => pct(n(row, "ATR %"), 2), value: (row) => n(row, "ATR %") },
    { key: "RSI", header: "RSI", align: "right", optional: true,
      render: (row) => num(n(row, "RSI"), 1), value: (row) => n(row, "RSI") },
    { key: "RelVol", header: "Rel vol", align: "right", optional: true,
      render: (row) => num(n(row, "RelVol"), 2), value: (row) => n(row, "RelVol") },
    { key: "Regime", header: "Regime", optional: true,
      render: (row) => <span className="text-2xs">{str(row, "Regime") || "—"}</span>,
      value: (row) => str(row, "Regime") },
  ];

  return (
    <Page>
      <PageHeader
        title="Early warning radar"
        description="Stocks approaching a trigger rather than already through it, ranked by how
          close they are and how compressed their range has become. This changes nothing about
          qualification — it builds a watchlist."
      />

      {job ? <JobProgress job={job} onDismiss={() => setRunId(null)} /> : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader title="Radar settings" icon={<Radar className="h-3.5 w-3.5 text-accent" />} />
          <CardBody className="space-y-5">
            <Field label="Universe">
              <CheckboxGroup
                columns={1}
                options={(universeOptions ?? []).map((universe) => ({
                  value: universe.name,
                  label: universe.name,
                  disabled: !universe.available,
                }))}
                selected={universes}
                onChange={setUniverses}
              />
            </Field>

            <Field label="Strategies">
              <CheckboxGroup options={STRATEGY_OPTIONS} selected={strategies}
                onChange={setStrategies} />
            </Field>

            <Field label="Rules allowed to fail" htmlFor="radar-missing"
              hint="0 reproduces the scanner's qualified list exactly. 2 is the useful default —
                close enough to matter, not so loose that everything appears.">
              <Select
                id="radar-missing"
                value={maxMissing}
                onChange={(event) => setMaxMissing(Number(event.target.value))}
              >
                {[0, 1, 2, 3, 4].map((value) => (
                  <option key={value} value={value}>
                    {value === 0 ? "0 — already qualifying" : `${value} rule${value === 1 ? "" : "s"}`}
                  </option>
                ))}
              </Select>
            </Field>

            <RangeField label="Minimum readiness" value={minReadiness} onChange={setMinReadiness}
              min={0} max={100} />

            <Button variant="primary" className="w-full" onClick={start}
              loading={startRadar.isPending || job?.status === "running"}
              disabled={universes.length === 0 || strategies.length === 0}>
              <Play className="h-3.5 w-3.5" aria-hidden />
              Run radar
            </Button>

            {(recentRuns ?? []).length > 0 ? (
              <div className="border-t border-line pt-3">
                <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-faint">
                  Recent runs
                </p>
                <ul className="space-y-0.5">
                  {(recentRuns ?? []).map((entry) => (
                    <li key={entry.id}>
                      <button
                        type="button"
                        onClick={() => setRunId(entry.id)}
                        className={cn(
                          "flex w-full items-center justify-between gap-2 rounded px-2 py-1.5",
                          "text-left text-2xs hover:bg-elevated",
                          entry.id === runId ? "bg-elevated text-ink" : "text-muted",
                        )}
                      >
                        <span>{relativeTime(entry.created_at)}</span>
                        <span className="tabular text-faint">{int(entry.row_count)} rows</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </CardBody>
        </Card>

        <div className="space-y-4 lg:col-span-2">
          {run.data ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Stocks on radar" value={int(rows.length)} />
              <Stat label="Scanned" value={int(stats.scanned as number)}
                sub={`${int(stats.too_short as number)} had too little history`} />
              <Stat label="Regime" value={String(stats.regime ?? "—")} />
            </div>
          ) : null}

          <Card className="overflow-hidden">
            {job?.status === "running" || job?.status === "queued" ? (
              <SkeletonTable rows={6} cols={7} />
            ) : run.error ? (
              <ErrorState error={run.error} />
            ) : (
              <DataTable
                rows={rows}
                columns={columns}
                getRowId={(row) => `${str(row, "Ticker")}|${str(row, "Strategy")}`}
                exportName="radar"
                sort={{ key: "Readiness", dir: "desc" }}
                emptyTitle={runId ? "Nothing is close enough" : "Run the radar to begin"}
                emptyMessage={
                  runId
                    ? "No stock is within the allowed number of failing rules. Try allowing one " +
                      "more, or lowering the readiness floor."
                    : "Pick a universe and how many rules a stock may still be failing."
                }
              />
            )}
          </Card>

          {blockingRules.length > 0 ? (
            <Card>
              <CardHeader
                title="What is blocking the market"
                description="The rules failing most often across the radar's results."
              />
              <div className="overflow-x-auto scroll-thin">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-line text-2xs uppercase tracking-wide
                      text-faint">
                      <th scope="col" className="px-4 py-2 text-left font-semibold">Rule</th>
                      <th scope="col" className="px-4 py-2 text-right font-semibold">Stocks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {blockingRules.slice(0, 12).map((row, index) => (
                      <tr key={index} className="border-b border-line/60 last:border-0">
                        <td className="px-4 py-1.5">
                          {str(row, "Rule") || str(row, "Missing Rule")}
                        </td>
                        <td className="tabular px-4 py-1.5 text-right">
                          {int(n(row, "Count") ?? n(row, "Stocks"))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : null}

          <Note>
            Readiness is a proximity measure, not a forecast. A stock at 90 readiness has not
            triggered and may never trigger — the scanner remains the only thing that decides
            whether a setup exists.
          </Note>
        </div>
      </div>
    </Page>
  );
}
