"use client";

import { BarChart3, FlaskConical, Play, Wallet } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge, toneForOutcome } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { CheckboxGroup, Field, Input, Select } from "@/components/ui/Inputs";
import { Note, ScoreBar, Stat, SymbolLink } from "@/components/ui/Misc";
import { EmptyState, ErrorState, Skeleton, SkeletonCards } from "@/components/ui/States";
import { JobProgress } from "@/features/scanner/JobProgress";
import { num as n, str } from "@/features/scanner/shared";
import {
  useDatasetStatus, useJob, useLatestBacktest, usePortfolio, useRun, useStartBacktest,
  useStartStudy, useUniverses,
} from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { compact, date, inr, int, num, pct, signed } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { BacktestStats, Row } from "@/types/api";

const PERIODS = ["6 Months", "1 Year", "2 Years", "3 Years"] as const;

const STUDIES = [
  { key: "raw-signals", label: "Raw strategy learning",
    description: "Simulates every S1-S4 signal with no score gate, so it becomes possible to " +
      "ask whether the score predicts anything at all." },
  { key: "sl-calibration", label: "Stop-loss calibration",
    description: "Five stop-placement schemes over the same signals and the same forward bars, " +
      "isolating the effect of placement alone." },
  { key: "s4-extension", label: "S4 EMA20 extension",
    description: "Tests whether the 3% extension cutoff is actually the best one." },
  { key: "s4-recovery", label: "S4 recovery study",
    description: "The research-only recovery structure, kept separate from the S4 rules until " +
      "it proves itself." },
] as const;

export function BacktestPage() {
  const [universes, setUniverses] = useState<string[]>(["Nifty 500"]);
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("1 Year");
  const [threshold, setThreshold] = useState(85);
  const [runId, setRunId] = useState<string | null>(null);
  const [studyId, setStudyId] = useState<string | null>(null);
  const [activeStudy, setActiveStudy] = useState<(typeof STUDIES)[number]["key"] | null>(null);

  const { data: universeOptions } = useUniverses();
  const dataset = useDatasetStatus(universes, period);
  const startBacktest = useStartBacktest();
  const latest = useLatestBacktest();
  const { data: job } = useJob(runId);
  const run = useRun(runId, job?.status === "succeeded");
  const { data: studyJob } = useJob(studyId);
  const studyRun = useRun(studyId, studyJob?.status === "succeeded");

  const rawStudy = useStartStudy("raw-signals");
  const slStudy = useStartStudy("sl-calibration");
  const extStudy = useStartStudy("s4-extension");
  const recoveryStudy = useStartStudy("s4-recovery");
  const studyMutations = {
    "raw-signals": rawStudy,
    "sl-calibration": slStudy,
    "s4-extension": extStudy,
    "s4-recovery": recoveryStudy,
  } as const;

  useEffect(() => {
    if (job?.status === "succeeded") latest.refetch();
  }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // A fresh run supersedes the stored one; otherwise the page opens on the
  // last backtest so it is never blank.
  const shown = run.data?.rows?.length ? run.data : latest.data;
  const rows = (shown?.rows ?? []) as Row[];
  const stats = (shown?.stats ?? {}) as Partial<BacktestStats>;

  async function start() {
    try {
      const started = await startBacktest.mutateAsync({ universes, period, threshold });
      setRunId(started.id);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  async function startStudy(key: (typeof STUDIES)[number]["key"]) {
    try {
      const started = await studyMutations[key].mutateAsync({ universes, period });
      setStudyId(started.id);
      setActiveStudy(key);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  const columns: Column<Row>[] = useMemo(() => [
    { key: "Ticker", header: "Symbol", sticky: true, width: "7.5rem",
      render: (row) => <SymbolLink symbol={str(row, "Ticker")} />,
      value: (row) => str(row, "Ticker") },
    { key: "Strategy", header: "Strategy",
      render: (row) => <Badge tone="accent">{str(row, "Strategy")}</Badge>,
      value: (row) => str(row, "Strategy") },
    { key: "Date", header: "Signal", render: (row) => date(str(row, "Date")),
      value: (row) => str(row, "Date") },
    { key: "Outcome", header: "Outcome",
      render: (row) => (
        <Badge tone={toneForOutcome(str(row, "Outcome"))}>{str(row, "Outcome")}</Badge>),
      value: (row) => str(row, "Outcome") },
    { key: "Score", header: "Score", align: "right",
      render: (row) => <ScoreBar score={n(row, "Score")} />, value: (row) => n(row, "Score") },
    { key: "Entry", header: "Entry", align: "right", render: (row) => inr(n(row, "Entry")),
      value: (row) => n(row, "Entry") },
    { key: "Exit", header: "Exit", align: "right", render: (row) => inr(n(row, "Exit")),
      value: (row) => n(row, "Exit") },
    { key: "Return %", header: "Return", align: "right",
      render: (row) => {
        const value = n(row, "Return %");
        return (
          <span className={cn(value !== null && value > 0 && "text-up",
            value !== null && value < 0 && "text-down")}>
            {pct(value, 2)}
          </span>
        );
      },
      value: (row) => n(row, "Return %") },
    { key: "R", header: "R", align: "right",
      render: (row) => {
        const value = n(row, "R");
        return (
          <span className={cn("font-semibold", value !== null && value > 0 && "text-up",
            value !== null && value <= 0 && "text-down")}>
            {signed(value, 2)}
          </span>
        );
      },
      value: (row) => n(row, "R") },
    { key: "Holding Bars", header: "Bars", align: "right",
      render: (row) => int(n(row, "Holding Bars")), value: (row) => n(row, "Holding Bars") },
    { key: "MFE %", header: "MFE", align: "right", optional: true,
      render: (row) => pct(n(row, "MFE %"), 1), value: (row) => n(row, "MFE %") },
    { key: "MAE %", header: "MAE", align: "right", optional: true,
      render: (row) => pct(n(row, "MAE %"), 1), value: (row) => n(row, "MAE %") },
    { key: "Regime", header: "Regime", optional: true,
      render: (row) => <span className="text-2xs">{str(row, "Regime")}</span>,
      value: (row) => str(row, "Regime") },
    { key: "≥85 Gate", header: "At gate", optional: true,
      render: (row) => (n(row, "≥85 Gate") ? <Badge tone="up">Yes</Badge> : "—"),
      value: (row) => n(row, "≥85 Gate") },
  ], []);

  return (
    <Page>
      <PageHeader
        title="Walk-forward backtest"
        description="Replays the local candle store bar by bar. It makes no Dhan calls — acquiring
          history is an explicit Data Manager action, so a study cannot change its own inputs
          while it runs."
      />

      {job ? <JobProgress job={job} onDismiss={() => setRunId(null)} /> : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Run configuration"
            icon={<BarChart3 className="h-3.5 w-3.5 text-accent" />} />
          <CardBody className="space-y-5">
            <Field label="Universe">
              <CheckboxGroup
                columns={1}
                options={(universeOptions ?? []).map((universe) => ({
                  value: universe.name, label: universe.name, disabled: !universe.available,
                }))}
                selected={universes}
                onChange={setUniverses}
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Period" htmlFor="bt-period">
                <Select id="bt-period" value={period}
                  onChange={(event) => setPeriod(event.target.value as typeof period)}>
                  {PERIODS.map((option) => <option key={option} value={option}>{option}</option>)}
                </Select>
              </Field>
              <Field label="Score gate" htmlFor="bt-threshold">
                <Input id="bt-threshold" type="number" min={0} max={100} value={threshold}
                  onChange={(event) => setThreshold(Number(event.target.value))} />
              </Field>
            </div>

            {dataset.data ? (
              <div className="space-y-2 rounded-md border border-line bg-elevated p-3">
                <p className="text-2xs font-semibold uppercase tracking-wide text-faint">
                  Local dataset
                </p>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <dt className="text-muted">Stocks ready</dt>
                  <dd className="tabular text-right font-semibold text-ink">
                    {int(dataset.data.ready)}
                  </dd>
                  <dt className="text-muted">Missing history</dt>
                  <dd className={cn("tabular text-right font-semibold",
                    dataset.data.missing > 0 ? "text-warn" : "text-ink")}>
                    {int(dataset.data.missing)}
                  </dd>
                  <dt className="text-muted">Local bars</dt>
                  <dd className="tabular text-right text-ink">
                    {compact(dataset.data.local_bars)}
                  </dd>
                  <dt className="text-muted">Signal window</dt>
                  <dd className="text-right text-2xs text-ink">
                    {date(dataset.data.start)} → {date(dataset.data.end)}
                  </dd>
                </dl>
                {dataset.data.missing > 0 ? (
                  <p className="text-2xs leading-relaxed text-warn">
                    The run will cover the {int(dataset.data.ready)} stocks that have enough
                    stored history. Sync the rest from Data Manager for full coverage.
                  </p>
                ) : null}
              </div>
            ) : (
              <Skeleton className="h-32 w-full" />
            )}

            <Button variant="primary" className="w-full" onClick={start}
              loading={startBacktest.isPending || job?.status === "running"}
              disabled={universes.length === 0 || (dataset.data?.ready ?? 0) === 0}>
              <Play className="h-3.5 w-3.5" aria-hidden />
              Run backtest
            </Button>
          </CardBody>
        </Card>

        <div className="space-y-4 lg:col-span-2">
          {latest.isLoading && !run.data ? (
            <SkeletonCards />
          ) : rows.length > 0 ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Stat label="Trades" value={int(stats.trades ?? rows.length)} />
                <Stat label="Strategies covered"
                  value={int((stats.by_strategy ?? []).length)} />
                <Stat label="Learning rows added"
                  value={int(stats.learning_observations_added)}
                  sub="Observations this run contributed" />
                <Stat label="Elapsed"
                  value={stats.elapsed_seconds ? `${num(stats.elapsed_seconds, 1)}s` : "—"}
                  sub="Zero API calls — local data only" />
              </div>

              {(stats.by_strategy ?? []).length > 0 ? (
                <Card>
                  <CardHeader title="Performance by strategy"
                    description="Win rate, expectancy and profit factor over the replayed
                      window." />
                  <div className="overflow-x-auto scroll-thin">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-line text-2xs uppercase tracking-wide
                          text-faint">
                          <th scope="col" className="px-4 py-2 text-left font-semibold">
                            Strategy
                          </th>
                          <th scope="col" className="px-4 py-2 text-right font-semibold">Trades</th>
                          <th scope="col" className="px-4 py-2 text-right font-semibold">Win %</th>
                          <th scope="col" className="px-4 py-2 text-right font-semibold">Avg R</th>
                          <th scope="col" className="px-4 py-2 text-right font-semibold">
                            Total R
                          </th>
                          <th scope="col" className="px-4 py-2 text-right font-semibold">
                            Profit factor
                          </th>
                          <th scope="col" className="px-4 py-2 text-right font-semibold">
                            Avg return
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {(stats.by_strategy ?? []).map((entry) => (
                          <tr key={entry.strategy} className="border-b border-line/60 last:border-0">
                            <td className="px-4 py-2 font-medium">{entry.strategy}</td>
                            <td className="tabular px-4 py-2 text-right">{int(entry.trades)}</td>
                            <td className={cn("tabular px-4 py-2 text-right",
                              entry.win_pct >= 50 ? "text-up" : "text-down")}>
                              {pct(entry.win_pct, 1)}
                            </td>
                            <td className={cn("tabular px-4 py-2 text-right font-medium",
                              entry.avg_r > 0 ? "text-up" : "text-down")}>
                              {signed(entry.avg_r, 3)}
                            </td>
                            <td className="tabular px-4 py-2 text-right">
                              {signed(entry.total_r)}
                            </td>
                            <td className="tabular px-4 py-2 text-right">
                              {num(entry.profit_factor, 2)}
                            </td>
                            <td className="tabular px-4 py-2 text-right">
                              {pct(entry.avg_return_pct)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              ) : null}

              {(stats.score_bands ?? []).length > 0 ? (
                <Card>
                  <CardHeader title="Does the score predict the outcome?"
                    description="Average R per score band over this run." />
                  <ScoreBandChart bands={stats.score_bands ?? []} />
                </Card>
              ) : null}

              <PortfolioSimulator rows={rows} />
            </>
          ) : (
            <Card>
              <EmptyState
                title="No backtest stored yet"
                message="Run one to build the historical dataset the learning engine feeds on.
                  The result is stored, so it is here next time you open this page."
              />
            </Card>
          )}
        </div>
      </div>

      {rows.length > 0 ? (
        <Card className="overflow-hidden">
          <CardHeader title="Every trade"
            description="One row per historical signal, with the outcome the walk-forward
              simulation measured." />
          <DataTable
            rows={rows}
            columns={columns}
            getRowId={(row) => `${str(row, "Ticker")}-${str(row, "Date")}-${str(row, "Strategy")}`}
            exportName="backtest-trades"
            emptyTitle="No trades"
          />
          <div className="border-t border-line px-3 py-2.5">
            <Note>
              A row exists only where every mandatory rule of its strategy passed. Historical
              results are research output, not a forecast: sample size, regime dependence and
              execution assumptions all limit what they can tell you.
            </Note>
          </div>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title="Research studies"
          description="Each runs over the same universe and period selected above."
          icon={<FlaskConical className="h-3.5 w-3.5 text-accent" />}
        />
        <CardBody className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            {STUDIES.map((study) => (
              <div key={study.key}
                className="flex flex-col justify-between gap-3 rounded-md border border-line
                  bg-elevated p-3">
                <div>
                  <p className="text-xs font-semibold text-ink">{study.label}</p>
                  <p className="mt-1 text-2xs leading-relaxed text-muted">{study.description}</p>
                </div>
                <Button size="sm" onClick={() => startStudy(study.key)}
                  loading={studyMutations[study.key].isPending}
                  disabled={universes.length === 0}>
                  Run study
                </Button>
              </div>
            ))}
          </div>

          {studyJob ? <JobProgress job={studyJob} onDismiss={() => setStudyId(null)} /> : null}

          {studyRun.data && (studyRun.data.rows ?? []).length > 0 ? (
            <Card className="overflow-hidden">
              <CardHeader
                title={STUDIES.find((study) => study.key === activeStudy)?.label ?? "Study result"}
                description={`${int((studyRun.data.rows ?? []).length)} rows`}
              />
              <StudyTable rows={studyRun.data.rows ?? []} columns={studyRun.data.columns ?? []} />
            </Card>
          ) : null}
        </CardBody>
      </Card>
    </Page>
  );
}

function ScoreBandChart({ bands }: { bands: Row[] }) {
  const data = bands.map((band) => ({
    band: str(band, "Band"),
    avgR: n(band, "avg_r") ?? 0,
    signals: n(band, "signals") ?? 0,
    winRate: n(band, "win_rate") ?? 0,
  }));

  return (
    <div className="space-y-2 p-4">
      <div className="h-44 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -20 }}>
            <CartesianGrid stroke="hsl(var(--line))" strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="band" tick={{ fill: "hsl(var(--faint))", fontSize: 11 }}
              axisLine={{ stroke: "hsl(var(--line))" }} tickLine={false} />
            <YAxis tick={{ fill: "hsl(var(--faint))", fontSize: 10 }} axisLine={false}
              tickLine={false} width={42} />
            <Tooltip
              cursor={{ fill: "hsl(var(--elevated))" }}
              contentStyle={{
                background: "hsl(var(--surface))",
                border: "1px solid hsl(var(--line))",
                borderRadius: 8, fontSize: 12, color: "hsl(var(--ink))",
              }}
              formatter={(value: number, key: string) =>
                key === "avgR" ? [num(value, 3), "Average R"] : [value, key]}
            />
            <Bar dataKey="avgR" radius={[3, 3, 0, 0]}>
              {data.map((entry, index) => (
                <Cell key={index}
                  fill={entry.avgR >= 0 ? "hsl(var(--up))" : "hsl(var(--down))"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="grid grid-cols-3 gap-2 text-2xs">
        {data.map((entry) => (
          <div key={entry.band} className="rounded border border-line bg-elevated px-2 py-1.5">
            <p className="font-semibold text-ink">{entry.band}</p>
            <p className="text-muted">
              {int(entry.signals)} trades · {pct(entry.winRate, 1)} won
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function StudyTable({ rows, columns }: { rows: Row[]; columns: string[] }) {
  const keys = columns.length > 0 ? columns : Object.keys(rows[0] ?? {});
  return (
    <div className="max-h-96 overflow-auto scroll-thin">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
            {keys.map((key) => (
              <th key={key} scope="col" className="whitespace-nowrap px-3 py-2 text-left
                font-semibold">
                {key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 300).map((row, index) => (
            <tr key={index} className="border-b border-line/60 last:border-0">
              {keys.map((key) => {
                const value = row[key];
                return (
                  <td key={key} className={cn("whitespace-nowrap px-3 py-1.5",
                    typeof value === "number" && "tabular text-right")}>
                    {value === null || value === undefined
                      ? <span className="text-faint">—</span>
                      : typeof value === "number"
                        ? num(value, Number.isInteger(value) ? 0 : 3)
                        : String(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PortfolioSimulator({ rows }: { rows: Row[] }) {
  const [capital, setCapital] = useState(100000);
  const [riskPct, setRiskPct] = useState(1);
  const [slots, setSlots] = useState(5);
  const portfolio = usePortfolio();

  return (
    <Card>
      <CardHeader
        title="Capital simulation"
        description="Fixed-fraction compounding over the realised R sequence. No overlapping-
          capital optimism, and no assumption that every signal could actually be taken."
        icon={<Wallet className="h-3.5 w-3.5 text-accent" />}
      />
      <CardBody className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Starting capital ₹" htmlFor="sim-capital">
            <Input id="sim-capital" type="number" min={1000} step={10000} value={capital}
              onChange={(event) => setCapital(Number(event.target.value))} />
          </Field>
          <Field label="Risk per trade %" htmlFor="sim-risk">
            <Input id="sim-risk" type="number" min={0.1} max={10} step={0.1} value={riskPct}
              onChange={(event) => setRiskPct(Number(event.target.value))} />
          </Field>
          <Field label="Capital slots" htmlFor="sim-slots">
            <Input id="sim-slots" type="number" min={1} max={50} value={slots}
              onChange={(event) => setSlots(Number(event.target.value))} />
          </Field>
          <div className="flex items-end">
            <Button variant="primary" className="w-full" loading={portfolio.isPending}
              onClick={() => portfolio.mutate({ rows, capital, risk_pct: riskPct, slots })}>
              Simulate
            </Button>
          </div>
        </div>

        {portfolio.data ? (
          <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-5">
            {Object.entries(portfolio.data).map(([key, value]) => (
              <div key={key} className="rounded-md border border-line bg-elevated p-2.5">
                <p className="text-2xs text-faint">{key}</p>
                <p className={cn("tabular mt-0.5 text-sm font-semibold",
                  key === "ROI %" && typeof value === "number"
                    ? value >= 0 ? "text-up" : "text-down"
                    : "text-ink")}>
                  {typeof value === "number" ? num(value, 2) : String(value)}
                </p>
              </div>
            ))}
          </div>
        ) : null}

        <Note>
          A simulated equity curve inherits every limitation of the backtest under it — slippage,
          liquidity and the assumption that each signal was actually takeable.
        </Note>
      </CardBody>
    </Card>
  );
}
