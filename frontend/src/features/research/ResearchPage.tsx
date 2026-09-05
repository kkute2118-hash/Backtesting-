"use client";

import { Beaker, Bot, Coins, Landmark, Play, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { CheckboxGroup, Field, Input, Select, Toggle } from "@/components/ui/Inputs";
import { Banner, Note, SymbolLink } from "@/components/ui/Misc";
import { EmptyState, Skeleton } from "@/components/ui/States";
import { JobProgress } from "@/features/scanner/JobProgress";
import { num as n, str } from "@/features/scanner/shared";
import {
  useConfig, useJob, useRun, useStartCustomScan, useStartSepaScan, useUniverses,
  useValidateDsl,
} from "@/hooks/queries";
import { api, errorMessage } from "@/lib/api";
import { int, num } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Job, Row } from "@/types/api";

type Tab = "custom" | "sepa" | "fundamentals" | "smc" | "ai";

const TABS: Array<{ key: Tab; label: string; icon: typeof Beaker }> = [
  { key: "custom", label: "Custom rules", icon: Beaker },
  { key: "sepa", label: "S4 SEPA", icon: Target },
  { key: "fundamentals", label: "Fundamentals", icon: Landmark },
  { key: "smc", label: "Forex / Crypto SMC", icon: Coins },
  { key: "ai", label: "AI panels", icon: Bot },
];

export function ResearchPage() {
  const [tab, setTab] = useState<Tab>("custom");

  return (
    <Page>
      <PageHeader
        title="Research lab"
        description="The engines that are deliberately kept out of the main scanner's path —
          custom rule sets, the S4 SEPA screen, fundamental enrichment, the separate crypto and
          forex research engine, and the optional AI panels."
      />

      <div className="flex flex-wrap items-center gap-0.5 rounded-md border border-line
        bg-elevated p-0.5" role="tablist" aria-label="Research tools">
        {TABS.map((entry) => {
          const Icon = entry.icon;
          return (
            <button
              key={entry.key}
              type="button"
              role="tab"
              aria-selected={tab === entry.key}
              onClick={() => setTab(entry.key)}
              className={cn(
                "flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium",
                "transition-colors",
                tab === entry.key ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink",
              )}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden />
              {entry.label}
            </button>
          );
        })}
      </div>

      {tab === "custom" ? <CustomStrategyPanel /> : null}
      {tab === "sepa" ? <SepaPanel /> : null}
      {tab === "fundamentals" ? <FundamentalsPanel /> : null}
      {tab === "smc" ? <SmcPanel /> : null}
      {tab === "ai" ? <AiPanel /> : null}
    </Page>
  );
}

/** Generic result table for the engines that return an arbitrary frame. */
function ResultFrame({ rows, columns, limit = 200 }: {
  rows: Row[]; columns?: string[]; limit?: number;
}) {
  const keys = columns && columns.length > 0 ? columns : Object.keys(rows[0] ?? {});
  return (
    <div className="max-h-[28rem] overflow-auto scroll-thin">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
            {keys.map((key) => (
              <th key={key} scope="col"
                className="whitespace-nowrap px-3 py-2 text-left font-semibold">{key}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, limit).map((row, index) => (
            <tr key={index} className="border-b border-line/60 last:border-0
              hover:bg-elevated/50">
              {keys.map((key) => {
                const value = row[key];
                const isSymbol = key === "Ticker" || key === "Symbol" || key === "symbol";
                return (
                  <td key={key} className={cn("whitespace-nowrap px-3 py-1.5",
                    typeof value === "number" && "tabular text-right")}>
                    {isSymbol && typeof value === "string"
                      ? <SymbolLink symbol={value} />
                      : value === null || value === undefined
                        ? <span className="text-faint">—</span>
                        : typeof value === "number"
                          ? num(value, Number.isInteger(value) ? 0 : 2)
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

const DSL_EXAMPLE = `# One rule per line, all ANDed together.
rsi14 > 55
close > 1.02 * ema20
relvol >= 1.5
vol20 > 100000`;

function CustomStrategyPanel() {
  const [rules, setRules] = useState(DSL_EXAMPLE);
  const [universes, setUniverses] = useState<string[]>(["Nifty 500"]);
  const [withBacktest, setWithBacktest] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);

  const { data: universeOptions } = useUniverses();
  const validate = useValidateDsl();
  const startScan = useStartCustomScan();
  const { data: job } = useJob(jobId);
  const run = useRun(jobId, job?.status === "succeeded");

  // Validate on a debounce so errors appear while typing, without a request
  // per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => validate.mutate(rules), 400);
    return () => clearTimeout(timer);
  }, [rules]); // eslint-disable-line react-hooks/exhaustive-deps

  const validation = validate.data;

  async function start() {
    try {
      const started = await startScan.mutateAsync({
        universes, rules, backtest: withBacktest, sl_pct: 0.07, target_r: 3.0,
      });
      setJobId(started.id);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-1">
        <CardHeader title="Rule set"
          description="A whitelist-only language — never evaluated as code. Every line must be
            COLUMN OP VALUE, and the values are the engine's own feature columns." />
        <CardBody className="space-y-4">
          <Field label="Rules" htmlFor="dsl-rules">
            <textarea
              id="dsl-rules"
              value={rules}
              onChange={(event) => setRules(event.target.value)}
              rows={10}
              spellCheck={false}
              className="w-full rounded-md border border-line bg-elevated px-2.5 py-2 font-mono
                text-xs text-ink hover:border-strongline focus:border-accent focus:outline-none"
            />
          </Field>

          {validation ? (
            validation.errors.length > 0 ? (
              <ul className="space-y-1">
                {validation.errors.map((error, index) => (
                  <li key={index}
                    className="rounded-md border border-down/30 bg-down-soft/30 px-2.5 py-1.5
                      text-2xs leading-relaxed text-ink">
                    {error}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-2xs text-up">
                {validation.conditions.length} rule
                {validation.conditions.length === 1 ? "" : "s"} parsed and valid.
              </p>
            )
          ) : null}

          <details className="rounded-md border border-line bg-elevated p-2.5">
            <summary className="cursor-pointer text-2xs font-medium text-muted">
              Available columns
            </summary>
            <div className="mt-2 flex flex-wrap gap-1">
              {(validation?.columns ?? []).map((column) => (
                <code key={column}
                  className="rounded bg-surface px-1.5 py-0.5 text-2xs text-muted">{column}</code>
              ))}
            </div>
          </details>

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

          <Toggle checked={withBacktest} onChange={setWithBacktest}
            label="Also backtest this rule set"
            description="Replays the same rules over the last two years with a 7% stop and a 3R
              target, so today's matches come with historical context." />

          <Button variant="primary" className="w-full" onClick={start}
            loading={startScan.isPending || job?.status === "running"}
            disabled={!validation?.valid || universes.length === 0}>
            <Play className="h-3.5 w-3.5" aria-hidden />
            Run rule set
          </Button>
        </CardBody>
      </Card>

      <div className="space-y-4 lg:col-span-2">
        {job ? <JobProgress job={job} onDismiss={() => setJobId(null)} /> : null}
        <Card className="overflow-hidden">
          <CardHeader title="Matches today"
            description={run.data ? `${int((run.data.rows ?? []).length)} stocks match every rule`
              : "Run the rule set to see which stocks match."} />
          {(run.data?.rows ?? []).length > 0 ? (
            <ResultFrame rows={run.data!.rows} columns={run.data!.columns} />
          ) : (
            <EmptyState title={jobId ? "Nothing matched" : "No results yet"}
              message={jobId
                ? "No stock in this universe satisfies every rule on the latest bar."
                : "Write a rule set and run it."} />
          )}
        </Card>

        {run.data?.backtest ? (
          <Card className="overflow-hidden">
            <CardHeader title="Historical result"
              description="The same rules replayed over the last two years." />
            <pre className="max-h-72 overflow-auto scroll-thin p-3 text-2xs leading-relaxed
              text-muted">
              {JSON.stringify(run.data.backtest, null, 2)}
            </pre>
          </Card>
        ) : null}

        <Note>
          A custom rule set is a research tool. It has no scoring, no safety gate and no learning
          overlay behind it — those belong to S1-S4 only.
        </Note>
      </div>
    </div>
  );
}

function SepaPanel() {
  const [universes, setUniverses] = useState<string[]>(["Nifty 500"]);
  const [minScore, setMinScore] = useState(60);
  const [withFundamentals, setWithFundamentals] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);

  const { data: universeOptions } = useUniverses();
  const startScan = useStartSepaScan();
  const { data: job } = useJob(jobId);
  const run = useRun(jobId, job?.status === "succeeded");

  async function start() {
    try {
      const started = await startScan.mutateAsync({
        universes, min_score: minScore, max_stocks: null,
        apply_fundamental_screen: withFundamentals,
      });
      setJobId(started.id);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <CardHeader title="S4 SEPA"
          description="Minervini-style stage analysis with its own quality score and stock DNA.
            The liquidity and price-action gate is applied first, as it is for every strategy." />
        <CardBody className="space-y-4">
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
          <Field label="Minimum SEPA score" htmlFor="sepa-score">
            <Input id="sepa-score" type="number" min={0} max={100} value={minScore}
              onChange={(event) => setMinScore(Number(event.target.value))} />
          </Field>
          <Toggle checked={withFundamentals} onChange={setWithFundamentals}
            label="Apply the fundamental screen"
            description="Adds a market-cap and fundamentals check per candidate. Needs Twelve
              Data, and is much slower because it is one request per stock." />
          <Button variant="primary" className="w-full" onClick={start}
            loading={startScan.isPending || job?.status === "running"}
            disabled={universes.length === 0}>
            <Play className="h-3.5 w-3.5" aria-hidden />
            Run SEPA scan
          </Button>
        </CardBody>
      </Card>

      <div className="space-y-4 lg:col-span-2">
        {job ? <JobProgress job={job} onDismiss={() => setJobId(null)} /> : null}
        <Card className="overflow-hidden">
          <CardHeader title="SEPA candidates"
            description={run.data ? `${int((run.data.rows ?? []).length)} candidates` : undefined} />
          {(run.data?.rows ?? []).length > 0 ? (
            <ResultFrame rows={run.data!.rows} columns={run.data!.columns} />
          ) : (
            <EmptyState title={jobId ? "No SEPA candidates" : "No results yet"}
              message={jobId
                ? "Nothing in this universe satisfies the SEPA entry rules at that score."
                : "Pick a universe and run the scan."} />
          )}
        </Card>
      </div>
    </div>
  );
}

function FundamentalsPanel() {
  const { data: config } = useConfig();
  const { data: universeOptions } = useUniverses();
  const [universes, setUniverses] = useState<string[]>(["Nifty 500"]);
  const [screens, setScreens] = useState<string[]>(["A", "B"]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const { data: job } = useJob(jobId);
  const run = useRun(jobId, job?.status === "succeeded");

  const configured = config?.providers.twelvedata.configured ?? false;

  async function start() {
    setPending(true);
    try {
      const started = await api.post<Job>("/fundamentals/screens", {
        universes: universes.filter((name) => !name.startsWith("NSE All")),
        run_a: screens.includes("A"),
        run_b: screens.includes("B"),
      });
      setJobId(started.id);
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-4">
      {!configured ? (
        <Banner tone="warn" title="Twelve Data is not configured">
          Fundamental screens, news risk and the forex/crypto engine all need TWELVEDATA_API_KEY
          in the backend environment. The equity scanner, backtests and forward tests work
          without it.
        </Banner>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Screen A / B"
            description="Long-term fundamental screens, run separately from the technical scan so
              expensive per-symbol requests never slow down a market-wide sweep." />
          <CardBody className="space-y-4">
            <Field label="Universe"
              hint="Index universes only — these screens walk the index CSVs.">
              <CheckboxGroup
                columns={1}
                options={(universeOptions ?? [])
                  .filter((universe) => !universe.requires_dhan)
                  .map((universe) => ({ value: universe.name, label: universe.name }))}
                selected={universes}
                onChange={setUniverses}
              />
            </Field>
            <Field label="Screens">
              <CheckboxGroup
                options={[{ value: "A", label: "Screen A" }, { value: "B", label: "Screen B" }]}
                selected={screens}
                onChange={setScreens}
              />
            </Field>
            <Button variant="primary" className="w-full" onClick={start} loading={pending}
              disabled={!configured || universes.length === 0 || screens.length === 0}>
              <Play className="h-3.5 w-3.5" aria-hidden />
              Run screens
            </Button>
          </CardBody>
        </Card>

        <div className="space-y-4 lg:col-span-2">
          {job ? <JobProgress job={job} onDismiss={() => setJobId(null)} /> : null}
          <Card className="overflow-hidden">
            <CardHeader title="Screen results" />
            {(run.data?.rows ?? []).length > 0 ? (
              <ResultFrame rows={run.data!.rows} columns={run.data!.columns} />
            ) : (
              <EmptyState title="No results yet"
                message="Screens take a while — one request per stock, rate-limited." />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function SmcPanel() {
  const { data: config } = useConfig();
  const [pairs, setPairs] = useState("EUR/USD, GBP/USD, USD/JPY");
  const [market, setMarket] = useState("Forex");
  const [minConfluence, setMinConfluence] = useState(2);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const { data: job } = useJob(jobId);
  const run = useRun(jobId, job?.status === "succeeded");
  const configured = config?.providers.twelvedata.configured ?? false;

  async function start() {
    setPending(true);
    try {
      const started = await api.post<Job>("/smc/scan", {
        pairs: pairs.split(",").map((pair) => pair.trim()).filter(Boolean),
        market,
        min_confluence: minConfluence,
      });
      setJobId(started.id);
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-4">
      {!configured ? (
        <Banner tone="warn" title="Twelve Data is not configured">
          The SMC engine reads 4-hour and 15-minute data through Twelve Data.
        </Banner>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Smart Money Concepts"
            description="A separate research engine on 4h structure and 15m triggers. It builds
              its own learning dataset rather than assuming the equity rules transfer." />
          <CardBody className="space-y-4">
            <Field label="Market" htmlFor="smc-market">
              <Select id="smc-market" value={market}
                onChange={(event) => setMarket(event.target.value)}>
                <option value="Forex">Forex</option>
                <option value="Crypto">Crypto</option>
              </Select>
            </Field>
            <Field label="Pairs" htmlFor="smc-pairs" hint="Comma separated, e.g. EUR/USD, BTC/USD">
              <Input id="smc-pairs" value={pairs}
                onChange={(event) => setPairs(event.target.value)} />
            </Field>
            <Field label="Minimum confluence" htmlFor="smc-confluence">
              <Input id="smc-confluence" type="number" min={0} max={6} value={minConfluence}
                onChange={(event) => setMinConfluence(Number(event.target.value))} />
            </Field>
            <Button variant="primary" className="w-full" onClick={start} loading={pending}
              disabled={!configured}>
              <Play className="h-3.5 w-3.5" aria-hidden />
              Scan pairs
            </Button>
          </CardBody>
        </Card>

        <div className="space-y-4 lg:col-span-2">
          {job ? <JobProgress job={job} onDismiss={() => setJobId(null)} /> : null}
          <Card className="overflow-hidden">
            <CardHeader title="Current setups" />
            {(run.data?.rows ?? []).length > 0 ? (
              <ResultFrame rows={run.data!.rows} columns={run.data!.columns} />
            ) : (
              <EmptyState title="No setups"
                message="No pair currently shows an SMC setup at that confluence." />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function AiPanel() {
  const { data: config } = useConfig();
  const [jobId, setJobId] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const { data: job } = useJob(jobId);
  const run = useRun(jobId, job?.status === "succeeded");
  const configured = config?.providers.anthropic.configured ?? false;

  async function start(path: string, label: string) {
    setPending(label);
    try {
      const started = await api.post<Job>(path);
      setJobId(started.id);
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setPending(null);
    }
  }

  const report = (run.data as unknown as { report?: string; panel?: unknown } | undefined);

  return (
    <div className="space-y-4">
      {!configured ? (
        <Banner tone="warn" title="No Anthropic key configured">
          The AI panels need ANTHROPIC_API_KEY in the backend environment. Everything else in the
          application works without it.
        </Banner>
      ) : null}

      <Card>
        <CardHeader
          title="AI panels"
          description="Written analysis of the evidence the engine has already accumulated. A
            panel cannot create, modify or approve a signal — the strategy rules stay
            authoritative, and a verdict is an opinion on candidates the scanner produced."
          icon={<Bot className="h-3.5 w-3.5 text-accent" />}
        />
        <CardBody className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2 rounded-md border border-line bg-elevated p-3">
              <p className="text-xs font-semibold text-ink">System coach</p>
              <p className="text-2xs leading-relaxed text-muted">
                Analyses the marking system as a whole — backtest performance, forward
                resolution, component correlations and the score-band edge table.
              </p>
              <Button size="sm" disabled={!configured} loading={pending === "coach"}
                onClick={() => start("/ai/coach", "coach")}>
                Run the coach
              </Button>
            </div>
            <div className="space-y-2 rounded-md border border-line bg-elevated p-3">
              <p className="text-xs font-semibold text-ink">System learning panel</p>
              <p className="text-2xs leading-relaxed text-muted">
                Five agents — strategy performance, marking components, risk and stops, a
                sceptic, and a judge — argue over the accumulated learning data.
              </p>
              <Button size="sm" disabled={!configured} loading={pending === "panel"}
                onClick={() => start("/ai/learning-panel", "panel")}>
                Run the panel
              </Button>
            </div>
          </div>

          {job ? <JobProgress job={job} onDismiss={() => setJobId(null)} /> : null}

          {report?.report ? (
            <div className="whitespace-pre-wrap rounded-md border border-line bg-elevated p-4
              text-xs leading-relaxed text-ink">
              {report.report}
            </div>
          ) : report?.panel ? (
            <pre className="max-h-96 overflow-auto scroll-thin rounded-md border border-line
              bg-elevated p-3 text-2xs leading-relaxed text-muted">
              {JSON.stringify(report.panel, null, 2)}
            </pre>
          ) : null}

          <Note>
            A language model reads the same tables you can. Treat its output as a second opinion
            on the evidence, not as a decision — and never as a reason to override a failing rule.
          </Note>
        </CardBody>
      </Card>
    </div>
  );
}
