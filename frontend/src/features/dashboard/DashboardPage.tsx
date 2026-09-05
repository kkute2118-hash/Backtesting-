"use client";

import {
  Activity, ArrowRight, Database, Layers, Radar, Target, TrendingUp, Wallet,
} from "lucide-react";
import Link from "next/link";

import { Badge, toneForSafety } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Note, ScoreBar, SectionTitle, Stat, SymbolLink } from "@/components/ui/Misc";
import { EmptyState, ErrorState, SkeletonCards, SkeletonTable } from "@/components/ui/States";
import { Page, PageHeader } from "@/components/layout/PageShell";
import { useOverview } from "@/hooks/queries";
import { compact, date, inr, int, num, relativeTime, signed } from "@/lib/format";
import type { Row } from "@/types/api";

import { BreadthChart } from "./BreadthChart";
import { FreshnessBanner } from "./FreshnessCard";

function n(row: Row, key: string): number | null {
  const value = row[key];
  return typeof value === "number" ? value : null;
}
function s(row: Row, key: string): string {
  const value = row[key];
  return value === null || value === undefined ? "" : String(value);
}

export function DashboardPage() {
  const { data, isLoading, error, refetch } = useOverview();

  if (isLoading) {
    return (
      <Page>
        <PageHeader title="Dashboard" description="Loading market and portfolio state…" />
        <SkeletonCards />
        <SkeletonTable rows={5} />
      </Page>
    );
  }

  if (error || !data) {
    return (
      <Page>
        <PageHeader title="Dashboard" />
        <ErrorState error={error} onRetry={() => refetch()} />
      </Page>
    );
  }

  const { market, data_store, freshness, forward, breadth, top_opportunities, latest_scan } = data;
  const totals = forward.totals;

  return (
    <Page>
      <PageHeader
        title="Dashboard"
        description={
          <>
            {market.exchange} {market.segment} is{" "}
            <span className={market.is_open ? "font-semibold text-up" : "font-semibold text-muted"}>
              {market.is_open ? "open" : "closed"}
            </span>
            . Last completed session {date(market.last_completed_session)}.
          </>
        }
        actions={
          <>
            <Link
              href="/radar"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line
                bg-elevated px-3 text-xs font-medium text-ink hover:border-strongline"
            >
              <Radar className="h-3.5 w-3.5" aria-hidden />
              Radar
            </Link>
            <Link
              href="/scanner"
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-accent px-3
                text-xs font-medium text-white hover:bg-accent/90"
            >
              <Target className="h-3.5 w-3.5" aria-hidden />
              Run a scan
            </Link>
          </>
        }
      />

      <FreshnessBanner
        freshness={freshness}
        action={
          freshness.severity === "error" ? (
            <Link
              href="/data"
              className="inline-flex h-7 items-center rounded-md border border-line px-2.5
                text-2xs font-medium text-ink hover:border-strongline"
            >
              Fix in Data Manager
            </Link>
          ) : undefined
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Open forward tests"
          value={int(totals.open)}
          sub={`${int(totals.closed)} closed · ${int(totals.total)} recorded in total`}
          icon={<Activity className="h-3.5 w-3.5" />}
        />
        <Stat
          label="Forward win rate"
          value={totals.win_rate === null ? "—" : `${num(totals.win_rate, 1)}%`}
          sub={
            totals.wins + totals.losses === 0
              ? "No trade has resolved yet"
              : `${totals.wins} won · ${totals.losses} lost`
          }
          tone={totals.win_rate === null ? undefined : totals.win_rate >= 50 ? "up" : "down"}
          icon={<TrendingUp className="h-3.5 w-3.5" />}
        />
        <Stat
          label="Total R"
          value={signed(totals.total_r)}
          sub={
            totals.avg_r === null
              ? "Awaiting resolved trades"
              : `${signed(totals.avg_r, 3)} average per trade`
          }
          tone={
            totals.total_r === null ? undefined : totals.total_r > 0 ? "up"
              : totals.total_r < 0 ? "down" : undefined
          }
          icon={<Wallet className="h-3.5 w-3.5" />}
        />
        <Stat
          label="Candle store"
          value={compact(data_store.bars)}
          sub={`${int(data_store.symbols)} stocks · newest ${date(data_store.latest_session)}`}
          icon={<Database className="h-3.5 w-3.5" />}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title="Top opportunities"
            description="The highest-scoring setups from the most recent recorded signal date."
            icon={<Layers className="h-3.5 w-3.5 text-accent" />}
            action={
              latest_scan ? (
                <Link
                  href={`/scanner/runs/${latest_scan.id}`}
                  className="inline-flex items-center gap-1 text-2xs font-medium text-accent
                    hover:underline"
                >
                  Open last scan
                  <ArrowRight className="h-3 w-3" aria-hidden />
                </Link>
              ) : null
            }
          />
          {top_opportunities.length === 0 ? (
            <EmptyState
              title="No signals recorded yet"
              message="Run a scan and any qualifying setup will be recorded here and ranked."
              action={
                <Link
                  href="/scanner"
                  className="inline-flex h-8 items-center rounded-md bg-accent px-3 text-xs
                    font-medium text-white hover:bg-accent/90"
                >
                  Open the scanner
                </Link>
              }
            />
          ) : (
            <div className="overflow-x-auto scroll-thin">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Symbol</th>
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Strategy</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Score</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Entry</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Stop</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Target</th>
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Safety</th>
                  </tr>
                </thead>
                <tbody>
                  {top_opportunities.map((row, index) => (
                    <tr key={`${s(row, "symbol")}-${s(row, "strategy")}-${index}`}
                      className="border-b border-line/60 last:border-0 hover:bg-elevated/50">
                      <td className="px-4 py-2"><SymbolLink symbol={s(row, "symbol")} /></td>
                      <td className="px-4 py-2">
                        <Badge tone="accent">{s(row, "strategy")}</Badge>
                      </td>
                      <td className="px-4 py-2 text-right"><ScoreBar score={n(row, "score")} /></td>
                      <td className="tabular px-4 py-2 text-right">{inr(n(row, "entry"))}</td>
                      <td className="tabular px-4 py-2 text-right text-down">
                        {inr(n(row, "stop"))}
                      </td>
                      <td className="tabular px-4 py-2 text-right text-up">
                        {inr(n(row, "target"))}
                      </td>
                      <td className="px-4 py-2">
                        <Badge tone={toneForSafety(s(row, "safety_status"))}>
                          {s(row, "safety_status") || "—"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="border-t border-line px-4 py-2.5">
            <Note>
              The score ranks setup quality against the engine&apos;s own components. It is not a
              probability of profit, and every row still needs your own review.
            </Note>
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Signal breadth"
              description={`Qualifying setups per day over the last ${breadth.window_days} days.`}
            />
            <BreadthChart data={breadth.daily} windowDays={breadth.window_days} />
          </Card>

          <Card>
            <CardHeader title="By strategy" description="Signals recorded in the same window." />
            <CardBody className="space-y-2.5 p-3.5">
              {breadth.by_strategy.length === 0 ? (
                <p className="px-1 py-3 text-xs text-muted">Nothing recorded yet.</p>
              ) : (
                breadth.by_strategy.map((entry) => {
                  const max = Math.max(...breadth.by_strategy.map((item) => item.signals), 1);
                  return (
                    <div key={entry.strategy} className="space-y-1">
                      <div className="flex items-baseline justify-between text-xs">
                        <span className="font-medium text-ink">{entry.strategy}</span>
                        <span className="tabular text-muted">
                          {entry.signals} signal{entry.signals === 1 ? "" : "s"}
                          {entry.at_gate > 0 ? (
                            <span className="text-up"> · {entry.at_gate} at gate</span>
                          ) : null}
                        </span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-elevated">
                        <div className="h-full rounded-full bg-accent"
                          style={{ width: `${(entry.signals / max) * 100}%` }} />
                      </div>
                    </div>
                  );
                })
              )}
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="space-y-3">
        <SectionTitle
          action={
            <Link href="/forward"
              className="inline-flex items-center gap-1 text-2xs font-medium text-accent
                hover:underline">
              Open the book
              <ArrowRight className="h-3 w-3" aria-hidden />
            </Link>
          }
        >
          Forward-test scorecard
        </SectionTitle>
        <Card>
          {forward.summary.length === 0 ? (
            <EmptyState
              title="No forward tests recorded"
              message="Send a qualifying setup to the forward-test book from a scan, and its
                outcome will be tracked here on completed daily candles."
            />
          ) : (
            <div className="overflow-x-auto scroll-thin">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Strategy</th>
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Status</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Records</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Open</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Closed</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Win %</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Avg R</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Total R</th>
                  </tr>
                </thead>
                <tbody>
                  {forward.summary.map((row, index) => (
                    <tr key={`${s(row, "Strategy")}-${index}`}
                      className="border-b border-line/60 last:border-0">
                      <td className="px-4 py-2 font-medium">{s(row, "Strategy")}</td>
                      <td className="px-4 py-2">
                        <Badge tone={
                          s(row, "Status") === "STRONG" ? "up"
                          : s(row, "Status") === "WEAK" ? "down"
                          : s(row, "Status") === "BUILDING SAMPLE" ? "neutral" : "warn"
                        }>
                          {s(row, "Status")}
                        </Badge>
                      </td>
                      <td className="tabular px-4 py-2 text-right">{int(n(row, "Records"))}</td>
                      <td className="tabular px-4 py-2 text-right">{int(n(row, "Open"))}</td>
                      <td className="tabular px-4 py-2 text-right">{int(n(row, "Closed"))}</td>
                      <td className="tabular px-4 py-2 text-right">
                        {n(row, "Win %") === null ? "—" : `${num(n(row, "Win %"), 1)}%`}
                      </td>
                      <td className="tabular px-4 py-2 text-right">{signed(n(row, "AvgR"), 3)}</td>
                      <td className="tabular px-4 py-2 text-right">{signed(n(row, "TotalR"))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {latest_scan ? (
        <Card>
          <CardHeader
            title="Last scan"
            description={
              `${latest_scan.universes.join(", ") || "—"} · S${latest_scan.strategies.join(", S")}`
            }
            action={
              <Link href={`/scanner/runs/${latest_scan.id}`}
                className="text-2xs font-medium text-accent hover:underline">
                View results
              </Link>
            }
          />
          <CardBody className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-muted">
            <span>
              <span className="tabular font-semibold text-ink">{int(latest_scan.row_count)}</span>{" "}
              qualifying setups
            </span>
            <span>{relativeTime(latest_scan.created_at)}</span>
            <Badge tone={latest_scan.status === "succeeded" ? "up" : "warn"}>
              {latest_scan.status}
            </Badge>
          </CardBody>
        </Card>
      ) : null}
    </Page>
  );
}
