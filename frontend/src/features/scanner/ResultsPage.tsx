"use client";

import {
  ArrowLeft, BadgeCheck, Bot, Layers, Send, ShieldAlert, Sparkles, TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge, toneForRegime, toneForSafety } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { SearchInput, useDebounced } from "@/components/ui/Inputs";
import { Change, Note, ScoreBar, Stat, SymbolLink } from "@/components/ui/Misc";
import { EmptyState, ErrorState, Progress, SkeletonTable } from "@/components/ui/States";
import { JobProgress } from "./JobProgress";
import {
  useAddForwardCandidates, useConfig, useDebatePanel, useFilteredResults, useJob, useRun,
  type ResultFilters,
} from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { inr, int, num, pct, ratio } from "@/lib/format";
import type { Row } from "@/types/api";

import { EMPTY_FILTERS, FilterPanel } from "./FilterPanel";
import { num as n, str } from "./shared";

const PAGE_SIZE = 100;

export function ResultsPage({ runId }: { runId: string }) {
  const [filters, setFilters] = useState<ResultFilters>({ ...EMPTY_FILTERS });
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({
    key: "Score", dir: "desc",
  });
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);

  const debouncedSearch = useDebounced(search, 250);

  const run = useRun(runId);
  // While the scan is still running the run endpoint reports progress instead
  // of rows, so the job is followed for the live message and percentage.
  const stillRunning = run.data?.status === "queued" || run.data?.status === "running";
  const { data: job } = useJob(stillRunning ? runId : null);

  const query = useMemo<ResultFilters>(
    () => ({
      ...filters,
      search: debouncedSearch,
      sort_by: sort.key,
      sort_dir: sort.dir,
      offset: page * PAGE_SIZE,
      limit: PAGE_SIZE,
    }),
    [filters, debouncedSearch, sort, page],
  );

  const results = useFilteredResults(runId, query, !stillRunning);
  const addForward = useAddForwardCandidates();

  const rows = results.data?.rows ?? [];
  const stats = results.data?.stats ?? run.data?.stats ?? {};
  const strategiesInRun = useMemo(() => {
    const seen = new Set<string>();
    (run.data?.rows ?? []).forEach((row) => {
      const value = str(row, "Strategy");
      if (value) seen.add(value);
    });
    return Array.from(seen).sort();
  }, [run.data?.rows]);

  const columns: Column<Row>[] = useMemo(
    () => [
      {
        key: "Ticker", header: "Symbol", sticky: true, width: "7.5rem",
        render: (row) => <SymbolLink symbol={str(row, "Ticker")} />,
        value: (row) => str(row, "Ticker"),
      },
      {
        key: "Strategy", header: "Strategy", width: "6.5rem",
        render: (row) => <Badge tone="accent">{str(row, "Strategy")}</Badge>,
        value: (row) => str(row, "Strategy"),
      },
      {
        key: "Score", header: "Score", align: "right", width: "6.5rem",
        render: (row) => <ScoreBar score={n(row, "Score")} />,
        value: (row) => n(row, "Score"),
        description: "Composite setup quality (0-100). A ranking, not a probability.",
      },
      {
        key: "Win Probability %", header: "Win prob", align: "right",
        render: (row) => {
          const value = n(row, "Win Probability %");
          return value === null
            ? <span className="text-faint" title="Not enough resolved trades yet">—</span>
            : <span className={value >= 55 ? "text-up" : value < 45 ? "text-down" : ""}>
                {pct(value, 1)}
              </span>;
        },
        value: (row) => n(row, "Win Probability %"),
        description: "From the trained classifier, or the score-band history when it is not " +
          "trained yet. Blank means there is not enough evidence.",
      },
      {
        key: "Entry", header: "Entry", align: "right",
        render: (row) => inr(n(row, "Entry")),
        value: (row) => n(row, "Entry"),
      },
      {
        key: "SL 7%", header: "Stop", align: "right",
        render: (row) => <span className="text-down">{inr(n(row, "SL 7%"))}</span>,
        value: (row) => n(row, "SL 7%"),
      },
      {
        key: "Target 3R", header: "Target", align: "right",
        render: (row) => <span className="text-up">{inr(n(row, "Target 3R"))}</span>,
        value: (row) => n(row, "Target 3R"),
      },
      {
        key: "R:R", header: "R:R", align: "right", sortable: false,
        render: (row) => str(row, "R:R") || "—",
        value: (row) => str(row, "R:R"),
      },
      {
        key: "RSI", header: "RSI", align: "right",
        render: (row) => num(n(row, "RSI"), 1),
        value: (row) => n(row, "RSI"),
      },
      {
        key: "RelVol", header: "Rel vol", align: "right",
        render: (row) => {
          const value = n(row, "RelVol");
          return (
            <span className={value !== null && value >= 1.5 ? "font-semibold text-up" : ""}>
              {ratio(value)}
            </span>
          );
        },
        value: (row) => n(row, "RelVol"),
        description: "Today's volume against its own 20-day average.",
      },
      {
        key: "Safety", header: "Safety", width: "6.5rem",
        render: (row) => (
          <Badge tone={toneForSafety(str(row, "Safety"))}>{str(row, "Safety") || "—"}</Badge>
        ),
        value: (row) => str(row, "Safety"),
      },
      {
        key: "Safety Score", header: "Safety score", align: "right", optional: true,
        render: (row) => num(n(row, "Safety Score"), 0),
        value: (row) => n(row, "Safety Score"),
      },
      {
        key: "Regime", header: "Regime", optional: true,
        render: (row) => (
          <Badge tone={toneForRegime(str(row, "Regime"))}>{str(row, "Regime") || "—"}</Badge>
        ),
        value: (row) => str(row, "Regime"),
      },
      {
        key: "Adaptive Score", header: "Adaptive", align: "right", optional: true,
        render: (row) => num(n(row, "Adaptive Score"), 1),
        value: (row) => n(row, "Adaptive Score"),
        description: "Score after the learning overlay. Strategy rules are unaffected.",
      },
      {
        key: "Learned Rank", header: "Learned rank", align: "right", optional: true,
        render: (row) => num(n(row, "Learned Rank"), 1),
        value: (row) => n(row, "Learned Rank"),
      },
      {
        key: "Historical Edge R", header: "Edge R", align: "right", optional: true,
        render: (row) => num(n(row, "Historical Edge R"), 3),
        value: (row) => n(row, "Historical Edge R"),
      },
      {
        key: "Learning Confidence", header: "Confidence", optional: true,
        render: (row) => (
          <span className="text-2xs text-muted">{str(row, "Learning Confidence") || "—"}</span>
        ),
        value: (row) => str(row, "Learning Confidence"),
      },
      {
        key: "HTF Score", header: "HTF demand", align: "right", optional: true,
        render: (row) => num(n(row, "HTF Score"), 0),
        value: (row) => n(row, "HTF Score"),
      },
      {
        key: "Footprint Score", header: "Footprint", align: "right", optional: true,
        render: (row) => num(n(row, "Footprint Score"), 0),
        value: (row) => n(row, "Footprint Score"),
      },
      {
        key: "Strategy Score", header: "Strategy score", align: "right", optional: true,
        render: (row) => num(n(row, "Strategy Score"), 0),
        value: (row) => n(row, "Strategy Score"),
      },
      {
        key: "Entry Quality", header: "Entry quality", align: "right", optional: true,
        render: (row) => num(n(row, "Entry Quality"), 0),
        value: (row) => n(row, "Entry Quality"),
      },
      {
        key: "Relative Strength", header: "Rel strength", align: "right", optional: true,
        render: (row) => num(n(row, "Relative Strength"), 0),
        value: (row) => n(row, "Relative Strength"),
      },
      {
        key: "Safety Flags", header: "Flags", optional: true, sortable: false,
        render: (row) => {
          const flags = str(row, "Safety Flags");
          return flags
            ? <span className="text-2xs text-warn" title={flags}>{flags}</span>
            : <span className="text-faint">—</span>;
        },
        value: (row) => str(row, "Safety Flags"),
      },
    ],
    [],
  );

  async function sendToForward() {
    const chosen = (run.data?.rows ?? []).filter((row) =>
      selected.includes(`${str(row, "Ticker")}|${str(row, "Strategy")}`));
    if (chosen.length === 0) return;
    try {
      const result = await addForward.mutateAsync(chosen);
      toast.success(
        result.added === 0
          ? "Already recorded — nothing new was added."
          : `${result.added} of ${result.submitted} recorded as forward tests.`,
      );
      setSelected([]);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  if (run.isLoading) {
    return (
      <Page>
        <PageHeader title="Scan results" />
        <SkeletonTable rows={8} cols={8} />
      </Page>
    );
  }

  if (run.error) {
    return (
      <Page>
        <PageHeader title="Scan results" />
        <ErrorState error={run.error} onRetry={() => run.refetch()} />
      </Page>
    );
  }

  if (stillRunning) {
    return (
      <Page>
        <PageHeader title="Scan in progress"
          description="Results appear here the moment the run finishes." />
        <Card>
          <CardBody className="space-y-3">
            <p className="text-sm text-ink">{job?.message ?? "Running…"}</p>
            <Progress value={job?.progress ?? 0} label="Scanning" />
          </CardBody>
        </Card>
      </Page>
    );
  }

  if (run.data?.status === "failed") {
    return (
      <Page>
        <PageHeader title="Scan failed" />
        <ErrorState error={new Error(run.data.error ?? "The scan did not complete.")} />
        <Link href="/scanner" className="text-xs font-medium text-accent hover:underline">
          Back to the scanner
        </Link>
      </Page>
    );
  }

  const request = (run.data?.request ?? {}) as {
    universes?: string[]; strategies?: number[]; min_score?: number; use_live_prices?: boolean;
  };
  const total = results.data?.total ?? run.data?.rows.length ?? 0;
  const filtered = results.data?.filtered ?? 0;
  const pages = Math.max(1, Math.ceil(filtered / PAGE_SIZE));
  const confluence = results.data?.confluence ?? [];

  return (
    <Page>
      <PageHeader
        title="Scan results"
        description={
          <>
            {(request.universes ?? []).join(", ") || "Universe"} ·{" "}
            {(request.strategies ?? []).map((strategy) => `S${strategy}`).join(", ")}
            {request.use_live_prices ? " · live intraday overlay" : " · last completed close"}
          </>
        }
        actions={
          <Link
            href="/scanner"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line
              bg-elevated px-3 text-xs font-medium text-ink hover:border-strongline"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            New scan
          </Link>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Stat label="Qualifying setups" value={int(total)}
          sub={`from ${int(stats.loaded as number)} stocks with enough history`} />
        <Stat label="Matching filters" value={int(filtered)}
          sub={filtered === total ? "No filters applied" : `${int(total - filtered)} filtered out`}
          tone={filtered === 0 && total > 0 ? "warn" : undefined} />
        <Stat label="Market regime" value={String(stats.regime ?? "—")}
          sub={`Regime score ${int(stats.regime_score as number)}`} />
        <Stat label="Excluded by safety gate" value={int(stats.safety_gate_excluded as number)}
          sub="Illiquid or manipulated-looking names, before any strategy ran"
          icon={<ShieldAlert className="h-3.5 w-3.5" />} />
        <Stat label="Multi-strategy" value={int(confluence.length)}
          sub="Stocks qualifying under more than one strategy"
          icon={<Layers className="h-3.5 w-3.5" />} />
      </div>

      <div className="flex gap-4">
        <FilterPanel
          value={filters}
          onChange={(next) => { setFilters(next); setPage(0); }}
          onReset={() => { setFilters({ ...EMPTY_FILTERS }); setPage(0); }}
          strategies={strategiesInRun}
        />

        <div className="min-w-0 flex-1 space-y-4">
          <Card className="overflow-hidden">
            <DataTable
              rows={rows}
              columns={columns}
              getRowId={(row) => `${str(row, "Ticker")}|${str(row, "Strategy")}`}
              selectable
              selected={selected}
              onSelectionChange={setSelected}
              sort={sort}
              onSortChange={(next) => { setSort(next); setPage(0); }}
              exportName="scan-results"
              emptyTitle={total === 0 ? "Nothing qualified" : "No stocks match your filters"}
              emptyMessage={
                total === 0
                  ? "Every stock failed at least one rule of every selected strategy. That is a " +
                    "normal outcome — the rules are strict by design."
                  : "Widen or clear the filters to see the rest of the run."
              }
              emptyAction={
                total > 0 ? (
                  <Button size="sm" onClick={() => { setFilters({ ...EMPTY_FILTERS }); setPage(0); }}>
                    Reset filters
                  </Button>
                ) : (
                  <Link href="/scanner"
                    className="inline-flex h-8 items-center rounded-md bg-accent px-3 text-xs
                      font-medium text-white hover:bg-accent/90">
                    Adjust the scan
                  </Link>
                )
              }
              toolbar={
                <>
                  <SearchInput
                    value={search}
                    onChange={(value) => { setSearch(value); setPage(0); }}
                    placeholder="Filter by symbol"
                    className="w-48"
                  />
                  {selected.length > 0 ? (
                    <Button
                      size="sm"
                      variant="primary"
                      loading={addForward.isPending}
                      onClick={sendToForward}
                    >
                      <Send className="h-3.5 w-3.5" aria-hidden />
                      Forward test {selected.length}
                    </Button>
                  ) : null}
                  <span className="text-2xs text-faint">
                    {int(filtered)} of {int(total)} shown
                  </span>
                </>
              }
            />
            {pages > 1 ? (
              <div className="flex items-center justify-between border-t border-line px-3 py-2">
                <Button size="sm" variant="ghost" disabled={page === 0}
                  onClick={() => setPage((current) => current - 1)}>
                  Previous
                </Button>
                <span className="tabular text-2xs text-muted">
                  Page {page + 1} of {pages}
                </span>
                <Button size="sm" variant="ghost" disabled={page >= pages - 1}
                  onClick={() => setPage((current) => current + 1)}>
                  Next
                </Button>
              </div>
            ) : null}
            <div className="border-t border-line px-3 py-2.5">
              <Note>
                Click any row to open its full analysis, including the rule-by-rule reason it
                qualified. Selecting rows and forward testing them records the signal and tracks
                its outcome on completed daily candles only.
              </Note>
            </div>
          </Card>

          {confluence.length > 0 ? (
            <Card>
              <CardHeader
                title="Multi-strategy confluence"
                description="These stocks passed every rule of more than one strategy on the
                  same day."
                icon={<Sparkles className="h-3.5 w-3.5 text-accent" />}
              />
              <div className="overflow-x-auto scroll-thin">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-line text-2xs uppercase tracking-wide
                      text-faint">
                      <th scope="col" className="px-4 py-2 text-left font-semibold">Symbol</th>
                      <th scope="col" className="px-4 py-2 text-left font-semibold">Strategies</th>
                      <th scope="col" className="px-4 py-2 text-right font-semibold">Best score</th>
                      <th scope="col" className="px-4 py-2 text-right font-semibold">Entry</th>
                      <th scope="col" className="px-4 py-2 text-left font-semibold">Safety</th>
                    </tr>
                  </thead>
                  <tbody>
                    {confluence.slice(0, 20).map((entry) => (
                      <tr key={entry.Ticker} className="border-b border-line/60 last:border-0">
                        <td className="px-4 py-2"><SymbolLink symbol={entry.Ticker} /></td>
                        <td className="px-4 py-2">
                          <div className="flex flex-wrap gap-1">
                            {entry.Strategies.map((strategy) => (
                              <Badge key={strategy} tone="accent">{strategy}</Badge>
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-2 text-right">
                          <ScoreBar score={entry["Best Score"]} />
                        </td>
                        <td className="tabular px-4 py-2 text-right">{inr(entry.Entry)}</td>
                        <td className="px-4 py-2">
                          <Badge tone={toneForSafety(entry.Safety)}>{entry.Safety || "—"}</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : null}

          <DebatePanel rows={rows} />

          <Diagnostics stats={stats} />
        </div>
      </div>
    </Page>
  );
}

/**
 * The five-agent trade debate.
 *
 * It argues over candidates the scanner already produced; it cannot create,
 * modify or approve a signal. The judge's ranking is an opinion on a shortlist,
 * not a decision, and it never overrides a failing rule.
 */
function DebatePanel({ rows }: { rows: Row[] }) {
  const { data: config } = useConfig();
  const [jobId, setJobId] = useState<string | null>(null);
  const debate = useDebatePanel();
  const { data: job } = useJob(jobId);
  const run = useRun(jobId, job?.status === "succeeded");

  const configured = config?.providers.anthropic.configured ?? false;
  const panel = (run.data as unknown as { panel?: Record<string, unknown> } | undefined)?.panel;

  return (
    <Card>
      <CardHeader
        title="AI trade debate panel"
        description="Five agents — technical, statistical sceptic, risk/capital, devil's
          advocate, judge — argue over the top candidates in this result."
        icon={<Bot className="h-3.5 w-3.5 text-accent" />}
        action={
          <Button
            size="sm"
            disabled={!configured || rows.length === 0}
            title={configured ? undefined : "Needs ANTHROPIC_API_KEY"}
            loading={debate.isPending || job?.status === "running"}
            onClick={async () => {
              try {
                const started = await debate.mutateAsync({ rows, target_count: 5 });
                setJobId(started.id);
              } catch (error) {
                toast.error(errorMessage(error));
              }
            }}
          >
            Run the panel
          </Button>
        }
      />
      <CardBody className="space-y-3">
        {!configured ? (
          <Note>
            The debate panel needs ANTHROPIC_API_KEY in the backend environment. Everything
            else on this page works without it.
          </Note>
        ) : null}
        {job ? <JobProgress job={job} onDismiss={() => setJobId(null)} /> : null}
        {panel ? (
          <pre className="max-h-96 overflow-auto scroll-thin rounded-md border border-line
            bg-elevated p-3 text-2xs leading-relaxed text-muted">
            {JSON.stringify(panel, null, 2)}
          </pre>
        ) : null}
      </CardBody>
    </Card>
  );
}


function Diagnostics({ stats }: { stats: Record<string, unknown> }) {
  const perStrategy = (stats.per_strategy ?? []) as Array<{
    strategy: string; signals: number; qualified: number;
  }>;
  const model = stats.ml_model as {
    ready: boolean; samples: number | null; min_samples: number | null;
    auc: number | null; reason: string | null;
  } | null;

  return (
    <Card>
      <CardHeader
        title="Scanner diagnostics"
        description="What the engine actually looked at, and why the count is what it is."
        icon={<BadgeCheck className="h-3.5 w-3.5 text-accent" />}
      />
      <CardBody className="space-y-4">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
          {[
            ["Universe size", stats.universe_size],
            ["Loaded from store", stats.loaded],
            ["Usable (260+ bars)", stats.usable],
            ["Too little history", stats.too_short],
          ].map(([label, value]) => (
            <div key={String(label)}>
              <dt className="text-2xs text-faint">{label as string}</dt>
              <dd className="tabular font-semibold text-ink">{int(value as number)}</dd>
            </div>
          ))}
        </dl>

        {perStrategy.length > 0 ? (
          <div>
            <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-faint">
              Per strategy
            </p>
            <div className="overflow-x-auto scroll-thin">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
                    <th scope="col" className="py-1.5 pr-4 text-left font-semibold">Strategy</th>
                    <th scope="col" className="px-4 py-1.5 text-right font-semibold">
                      Raw signals
                    </th>
                    <th scope="col" className="px-4 py-1.5 text-right font-semibold">
                      Scored setups
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {perStrategy.map((entry) => (
                    <tr key={entry.strategy} className="border-b border-line/60 last:border-0">
                      <td className="py-1.5 pr-4 font-medium">{entry.strategy}</td>
                      <td className="tabular px-4 py-1.5 text-right">{int(entry.signals)}</td>
                      <td className="tabular px-4 py-1.5 text-right">{int(entry.qualified)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        {model ? (
          model.ready ? (
            <p className="flex items-start gap-1.5 text-2xs leading-relaxed text-muted">
              <BadgeCheck className="mt-px h-3 w-3 shrink-0 text-up" aria-hidden />
              Win probability comes from a classifier trained on{" "}
              {int(model.samples)} resolved trades
              {model.auc !== null ? ` (held-out AUC ${num(model.auc, 3)})` : ""}.
            </p>
          ) : (
            <p className="flex items-start gap-1.5 text-2xs leading-relaxed text-warn">
              <TriangleAlert className="mt-px h-3 w-3 shrink-0" aria-hidden />
              The win-probability model is not trained yet —{" "}
              {model.reason ?? `${int(model.samples)} of ${int(model.min_samples)} resolved trades
                so far`}. The column falls back to the score-band history, and is blank where even
              that has too small a sample.
            </p>
          )
        ) : null}
      </CardBody>
    </Card>
  );
}
