"use client";

import { Download, History, Play, Target, Zap } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { CheckboxGroup, Field, RangeField, Select, Toggle } from "@/components/ui/Inputs";
import { Note } from "@/components/ui/Misc";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { FreshnessBanner } from "@/features/dashboard/FreshnessCard";
import {
  useFreshness, useJob, useScanRuns, useStartScan, useSyncLatest, useUniverses,
} from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { int, relativeTime } from "@/lib/format";

import { JobProgress } from "./JobProgress";
import { PresetBar } from "./PresetBar";
import { DEFAULT_SCAN, STRATEGY_OPTIONS, type ScanFormState } from "./shared";

/**
 * Scanner controls.
 *
 * The three inputs that change what the *engine* evaluates — universe,
 * strategies, live overlay — sit together above an explicit Run button, and
 * everything that only narrows the answer lives on the results page. That
 * separation is why a slider drag no longer re-scans two thousand stocks.
 */
export function ScannerPage() {
  const router = useRouter();
  const [form, setForm] = useState<ScanFormState>(DEFAULT_SCAN);
  const [jobId, setJobId] = useState<string | null>(null);

  const { data: universes, isLoading: universesLoading, error: universesError } = useUniverses();
  const { data: freshness, error: freshnessError } = useFreshness(form.universes);
  const { data: runs } = useScanRuns(8);
  const startScan = useStartScan();
  const syncLatest = useSyncLatest();
  const { data: job } = useJob(jobId);

  // A finished scan takes the user straight to its results, which is where the
  // work continues — there is nothing more to do on this page once it is done.
  useEffect(() => {
    // Only a scan has results to open; a top-up job finishes in place.
    if (job?.status === "succeeded" && job.kind === "scan") {
      router.push(`/scanner/runs/${job.id}`);
    }
  }, [job?.status, job?.id, job?.kind, router]);

  function set<K extends keyof ScanFormState>(key: K, value: ScanFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function topUp() {
    try {
      const started = await syncLatest.mutateAsync({ universes: form.universes });
      setJobId(started.id);
      toast.success("Fetching the newest sessions");
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  async function run() {
    try {
      const started = await startScan.mutateAsync({
        universes: form.universes,
        strategies: form.strategies,
        min_score: form.min_score,
        use_live_prices: form.use_live_prices,
        limit: form.limit,
      });
      setJobId(started.id);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  const canRun = form.universes.length > 0 && form.strategies.length > 0;
  const isRunning = job?.status === "queued" || job?.status === "running";

  return (
    <Page>
      <PageHeader
        title="Stock scanner"
        description="Every selected stock is tested independently against every selected strategy.
          A stock appears under a strategy only when all of that strategy's rules pass; the score
          ranks the survivors, it never promotes a stock past a failing rule."
      />

      <FreshnessBanner
        freshness={freshness}
        error={freshnessError}
        action={
          freshness && freshness.severity === "error" ? (
            <Button
              size="sm"
              variant="primary"
              loading={syncLatest.isPending}
              onClick={topUp}
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
              Top up now
            </Button>
          ) : undefined
        }
      />

      {job ? <JobProgress job={job} onDismiss={() => setJobId(null)} /> : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Scan configuration"
            description="These change what the engine evaluates, so each run is a fresh scan."
            icon={<Target className="h-3.5 w-3.5 text-accent" />}
          />
          <CardBody className="space-y-5">
            {universesLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : universesError ? (
              <ErrorState error={universesError} compact />
            ) : (
              <Field
                label="Universe"
                hint="The full NSE list is roughly four times Nifty 500 and takes proportionally
                  longer. It is built from Dhan's instrument master, so it needs Dhan credentials."
              >
                <CheckboxGroup
                  columns={2}
                  options={(universes ?? []).map((universe) => ({
                    value: universe.name,
                    label: universe.name,
                    disabled: !universe.available,
                    hint: universe.available
                      ? universe.source
                      : `${universe.source} — Dhan is not configured`,
                  }))}
                  selected={form.universes}
                  onChange={(next) => set("universes", next)}
                />
              </Field>
            )}

            <Field
              label="Strategies"
              hint="Each is evaluated independently. A stock can qualify under more than one."
            >
              <CheckboxGroup
                options={STRATEGY_OPTIONS}
                selected={form.strategies}
                onChange={(next) => set("strategies", next)}
              />
            </Field>

            <div className="grid gap-5 sm:grid-cols-2">
              <RangeField
                label="Forward-test gate"
                value={form.min_score}
                onChange={(next) => set("min_score", next)}
                min={0}
                max={100}
                hint="Signals at or above this score are marked for forward testing when the run
                  is recorded. Everything qualifying is still returned and rankable."
              />
              <Field label="Result cap" htmlFor="scan-limit"
                hint="Cap what the run returns. Leave at all for a full research sweep.">
                <Select
                  id="scan-limit"
                  value={form.limit ?? ""}
                  onChange={(event) =>
                    set("limit", event.target.value === "" ? null : Number(event.target.value))
                  }
                >
                  <option value="">All qualifying setups</option>
                  <option value="10">Top 10</option>
                  <option value="25">Top 25</option>
                  <option value="50">Top 50</option>
                  <option value="100">Top 100</option>
                </Select>
              </Field>
            </div>

            <Toggle
              checked={form.use_live_prices}
              onChange={(next) => set("use_live_prices", next)}
              label="Scan against today's live price"
              description="Overlays today's still-forming candle from Dhan's quote feed on top of
                the stored history, in memory only. Stored candles are never overwritten with a
                partial bar. Meaningful during the cash session; outside it the last close already
                is the latest price."
            />

            <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
              <Button
                variant="primary"
                size="lg"
                onClick={run}
                disabled={!canRun || isRunning}
                loading={startScan.isPending || isRunning}
              >
                <Play className="h-3.5 w-3.5" aria-hidden />
                {isRunning ? "Scanning…" : "Run scan"}
              </Button>
              {!canRun ? (
                <p className="text-2xs text-warn">
                  Select at least one universe and one strategy.
                </p>
              ) : null}
            </div>

            <Note>
              A scan reads the local candle store and makes no Dhan calls unless the live overlay
              is on. If the store is stale, top it up from Data Manager first — scanning old
              closes produces late entries.
            </Note>
          </CardBody>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Presets" description="Configurations you return to."
              icon={<Zap className="h-3.5 w-3.5 text-accent" />} />
            <CardBody>
              <PresetBar
                current={form}
                onApply={(preset) =>
                  setForm({
                    universes: preset.config.universes,
                    strategies: preset.config.strategies,
                    min_score: preset.config.min_score,
                    use_live_prices: preset.config.use_live_prices,
                    limit: preset.config.limit,
                  })
                }
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Recent runs" description="Results stay addressable by URL."
              icon={<History className="h-3.5 w-3.5 text-accent" />} />
            <CardBody className="p-2">
              {(runs ?? []).length === 0 ? (
                <p className="px-2 py-4 text-center text-xs text-muted">No scans yet.</p>
              ) : (
                <ul className="space-y-0.5">
                  {(runs ?? []).map((run) => {
                    const request = run.request as { universes?: string[]; strategies?: number[] };
                    return (
                      <li key={run.id}>
                        <Link
                          href={`/scanner/runs/${run.id}`}
                          className="flex items-center gap-2 rounded-md px-2 py-1.5
                            hover:bg-elevated"
                        >
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-xs font-medium text-ink">
                              {(request.universes ?? []).join(", ") || "Scan"}
                            </p>
                            <p className="text-2xs text-faint">
                              {relativeTime(run.created_at)} ·{" "}
                              {int(run.row_count)} setup{run.row_count === 1 ? "" : "s"}
                            </p>
                          </div>
                          <Badge tone={
                            run.status === "succeeded" ? "up"
                            : run.status === "failed" ? "down" : "warn"
                          }>
                            {run.status}
                          </Badge>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </Page>
  );
}
