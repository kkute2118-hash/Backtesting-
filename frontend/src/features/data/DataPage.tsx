"use client";

import {
  CloudDownload, CloudUpload, Database, Download, KeyRound, Radio, Stethoscope,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { CheckboxGroup, Field, Select } from "@/components/ui/Inputs";
import { Banner, Note, Stat } from "@/components/ui/Misc";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { FreshnessBanner } from "@/features/dashboard/FreshnessCard";
import { JobProgress } from "@/features/scanner/JobProgress";
import {
  useBackupDiagnostic, useBackupStatus, useConfig, useConnectionTest, useDataStore,
  useFreshness, useJob, useRenewToken, useRestoreBackup, useRunBackup, useRunDiagnostics,
  useSmokeTest, useStoredDiagnostics, useSyncFull, useSyncLatest, useUniverses,
} from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { compact, date, int, relativeTime } from "@/lib/format";

const PERIODS = ["6 Months", "1 Year", "2 Years", "3 Years"] as const;

export function DataPage() {
  const [universes, setUniverses] = useState<string[]>(["Nifty 500"]);
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("2 Years");
  const [jobId, setJobId] = useState<string | null>(null);

  const { data: config } = useConfig();
  const { data: universeOptions } = useUniverses();
  const store = useDataStore();
  const backup = useBackupStatus();
  const freshness = useFreshness(universes);
  const diagnostics = useStoredDiagnostics();
  const { data: job } = useJob(jobId);

  const syncLatest = useSyncLatest();
  const syncFull = useSyncFull();
  const runDiagnostics = useRunDiagnostics();
  const connectionTest = useConnectionTest();
  const backupNow = useRunBackup();
  const restoreNow = useRestoreBackup();
  const backupDiagnostic = useBackupDiagnostic();
  const renewToken = useRenewToken();
  const smokeTest = useSmokeTest();

  const dhanConfigured = config?.providers.dhan.configured ?? false;

  async function launch(
    action: () => Promise<{ id: string }>,
    label: string,
  ) {
    try {
      const started = await action();
      setJobId(started.id);
      toast.success(`${label} started`);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <Page>
      <PageHeader
        title="Data manager"
        description="Acquisition is always explicit here. No page load, scan or backtest
          downloads anything — that is what keeps a study's inputs fixed while it runs and keeps
          the rate-limited Dhan budget under your control."
      />

      {!dhanConfigured ? (
        <Banner tone="warn" title="Dhan is not configured">
          Set DHAN_CLIENT_ID plus DHAN_PIN and DHAN_TOTP_SECRET (or DHAN_ACCESS_TOKEN) in the
          backend environment. Without them the app can still scan, backtest and learn from
          whatever history is already stored, but it cannot fetch anything new.
        </Banner>
      ) : null}

      <FreshnessBanner freshness={freshness.data} error={freshness.error} />
      {job ? <JobProgress job={job} onDismiss={() => setJobId(null)} /> : null}

      {store.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : store.error ? (
        <ErrorState error={store.error} onRetry={() => store.refetch()} />
      ) : store.data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat label="Stored candles" value={compact(store.data.bars)}
            icon={<Database className="h-3.5 w-3.5" />} />
          <Stat label="Stocks" value={int(store.data.symbols)}
            sub={`${int(store.data.thin_symbols.length)} below the 260-bar threshold`} />
          <Stat label="Newest session" value={date(store.data.latest_session)}
            sub={`Earliest ${date(store.data.earliest_session)}`} />
          <Stat label="Backup"
            value={backup.data?.configured ? "Configured" : "Off"}
            tone={backup.data?.configured ? "up" : "warn"}
            sub={backup.data?.configured
              ? `${backup.data.repo} · ${backup.data.branch}`
              : "Accumulated learning is not protected"} />
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Sync" description="Choose what to fetch, then fetch it."
            icon={<Download className="h-3.5 w-3.5 text-accent" />} />
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

            <div className="space-y-2 border-t border-line pt-3">
              <Button
                variant="primary"
                className="w-full"
                disabled={!dhanConfigured || universes.length === 0}
                loading={syncLatest.isPending}
                onClick={() => launch(
                  () => syncLatest.mutateAsync({ universes }), "Top-up")}
              >
                Top up latest sessions
              </Button>
              <p className="text-2xs leading-relaxed text-faint">
                Requests only the last {store.data?.tail_days ?? 10} days per stock and
                re-requests the newest stored bars, so a candle first written mid-session is
                corrected once it really closes. Minutes, not hours.
              </p>
            </div>

            <div className="space-y-2 border-t border-line pt-3">
              <Field label="Full sync window" htmlFor="sync-period">
                <Select id="sync-period" value={period}
                  onChange={(event) => setPeriod(event.target.value as typeof period)}>
                  {PERIODS.map((option) => <option key={option} value={option}>{option}</option>)}
                </Select>
              </Field>
              <Button
                className="w-full"
                disabled={!dhanConfigured || universes.length === 0}
                loading={syncFull.isPending}
                onClick={() => launch(
                  () => syncFull.mutateAsync({ universes, period }), "Full sync")}
              >
                Sync missing history
              </Button>
              <p className="text-2xs leading-relaxed text-faint">
                Walks the whole window per stock and fills every gap. Slow, and rate-limited to
                five requests a second — run it once to build the store, then top up daily.
              </p>
            </div>

            <div className="border-t border-line pt-3">
              <Button
                variant="ghost"
                className="w-full"
                disabled={universes.length === 0}
                loading={runDiagnostics.isPending}
                onClick={() => launch(
                  () => runDiagnostics.mutateAsync({ universes }), "Diagnostics")}
              >
                <Stethoscope className="h-3.5 w-3.5" aria-hidden />
                Diagnose thin symbols
              </Button>
            </div>
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader
            title="Database backup"
            description="Forward tests, resolved outcomes and accumulated learning cannot be
              rebuilt from anywhere. Candles can — one sync brings them back."
            icon={<CloudUpload className="h-3.5 w-3.5 text-accent" />}
          />
          <CardBody className="space-y-4">
            {backup.data?.configured ? (
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
                <div>
                  <dt className="text-2xs text-faint">Repository</dt>
                  <dd className="truncate font-medium text-ink">{backup.data.repo}</dd>
                </div>
                <div>
                  <dt className="text-2xs text-faint">Branch</dt>
                  <dd className="font-medium text-ink">{backup.data.branch}</dd>
                </div>
                <div>
                  <dt className="text-2xs text-faint">Rows in database</dt>
                  <dd className="tabular font-medium text-ink">{compact(backup.data.db_rows)}</dd>
                </div>
                <div>
                  <dt className="text-2xs text-faint">Last error</dt>
                  <dd className="truncate font-medium text-ink">
                    {backup.data.last_error || "None"}
                  </dd>
                </div>
              </dl>
            ) : (
              <Banner tone="warn" title="No backup configured">
                Set GH_BACKUP_TOKEN and GH_REPO, and a dedicated DB_BACKUP_BRANCH. Without them a
                container restart takes your forward tests and learning history with it.
              </Banner>
            )}

            <div className="flex flex-wrap gap-2">
              <Button size="sm" loading={backupNow.isPending}
                disabled={!backup.data?.configured}
                onClick={() => backupNow.mutate(undefined, {
                  onSuccess: (result) => toast.success(result.message),
                  onError: (error) => toast.error(errorMessage(error)),
                })}>
                <CloudUpload className="h-3.5 w-3.5" aria-hidden />
                Back up now
              </Button>
              <Button size="sm" loading={restoreNow.isPending}
                disabled={!backup.data?.configured}
                onClick={() => restoreNow.mutate(undefined, {
                  onSuccess: (result) => toast.success(result.message),
                  onError: (error) => toast.error(errorMessage(error)),
                })}>
                <CloudDownload className="h-3.5 w-3.5" aria-hidden />
                Restore
              </Button>
              <Button size="sm" variant="ghost" loading={backupDiagnostic.isPending}
                onClick={() => backupDiagnostic.mutate(undefined, {
                  onSuccess: () => toast.success("Diagnostic complete — see the report below"),
                  onError: (error) => toast.error(errorMessage(error)),
                })}>
                <Stethoscope className="h-3.5 w-3.5" aria-hidden />
                Test the backup path
              </Button>
              <Button size="sm" variant="ghost" loading={connectionTest.isPending}
                onClick={() => connectionTest.mutate(undefined, {
                  onSuccess: () => toast.success("Dhan connectivity checked"),
                  onError: (error) => toast.error(errorMessage(error)),
                })}>
                <Radio className="h-3.5 w-3.5" aria-hidden />
                Test Dhan connection
              </Button>
              <Button size="sm" variant="ghost" loading={smokeTest.isPending}
                disabled={!dhanConfigured}
                title="Downloads 30 days of RELIANCE and reports exactly what came back"
                onClick={() => smokeTest.mutate("RELIANCE", {
                  onSuccess: () => toast.success("Smoke test complete — see the report below"),
                  onError: (error) => toast.error(errorMessage(error)),
                })}>
                <Stethoscope className="h-3.5 w-3.5" aria-hidden />
                Historical smoke test
              </Button>
              <Button size="sm" variant="ghost" loading={renewToken.isPending}
                disabled={!config?.providers.dhan.auto_renew}
                title={config?.providers.dhan.auto_renew
                  ? undefined
                  : "Needs DHAN_PIN and DHAN_TOTP_SECRET"}
                onClick={() => renewToken.mutate(undefined, {
                  onSuccess: () => toast.success("A fresh Dhan token was minted"),
                  onError: (error) => toast.error(errorMessage(error)),
                })}>
                <KeyRound className="h-3.5 w-3.5" aria-hidden />
                Renew Dhan token
              </Button>
            </div>

            {backupDiagnostic.data ? (
              <pre className="max-h-64 overflow-auto scroll-thin rounded-md border border-line
                bg-elevated p-3 text-2xs leading-relaxed text-muted">
                {JSON.stringify(backupDiagnostic.data.result, null, 2)}
              </pre>
            ) : null}

            {smokeTest.data ? (
              <pre className="max-h-64 overflow-auto scroll-thin rounded-md border border-line
                bg-elevated p-3 text-2xs leading-relaxed text-muted">
                {JSON.stringify(smokeTest.data.result, null, 2)}
              </pre>
            ) : null}

            {connectionTest.data ? (
              <pre className="max-h-64 overflow-auto scroll-thin rounded-md border border-line
                bg-elevated p-3 text-2xs leading-relaxed text-muted">
                {JSON.stringify(connectionTest.data.checks, null, 2)}
              </pre>
            ) : null}

            <Note>
              The two secret stores are separate: this server reads its own environment, and the
              scheduled GitHub Actions jobs read Actions secrets. Configuring one does not
              configure the other.
            </Note>
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Stocks with thin history"
            description="Below the 260 bars the multi-timeframe engine needs." />
          {(store.data?.thin_symbols ?? []).length === 0 ? (
            <EmptyState title="Every stored stock has enough history"
              message="Nothing in the store is below the threshold." />
          ) : (
            <div className="max-h-72 overflow-auto scroll-thin">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface">
                  <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Symbol</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Bars</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Newest</th>
                  </tr>
                </thead>
                <tbody>
                  {(store.data?.thin_symbols ?? []).map((entry) => (
                    <tr key={entry.symbol} className="border-b border-line/60 last:border-0">
                      <td className="px-4 py-1.5 font-medium">{entry.symbol}</td>
                      <td className="tabular px-4 py-1.5 text-right text-warn">
                        {int(entry.bars)}
                      </td>
                      <td className="px-4 py-1.5 text-right text-faint">{date(entry.latest)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="Why symbols are thin"
            description="Not in Dhan's instrument master, a real API error, or simply recently
              listed." />
          {(diagnostics.data?.rows ?? []).length === 0 ? (
            <EmptyState title="No diagnostics recorded"
              message="Run “Diagnose thin symbols” to classify every stock below the threshold." />
          ) : (
            <div className="max-h-72 overflow-auto scroll-thin">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface">
                  <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Symbol</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Bars</th>
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {(diagnostics.data?.rows ?? []).map((row, index) => (
                    <tr key={index} className="border-b border-line/60 last:border-0">
                      <td className="px-4 py-1.5 font-medium">{String(row.symbol ?? "")}</td>
                      <td className="tabular px-4 py-1.5 text-right">
                        {int(row.bar_count as number)}
                      </td>
                      <td className="px-4 py-1.5 text-muted">{String(row.reason ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {(store.data?.sync_log ?? []).length > 0 ? (
        <Card>
          <CardHeader title="Sync history" />
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
                  <th scope="col" className="px-4 py-2 text-left font-semibold">When</th>
                  <th scope="col" className="px-4 py-2 text-left font-semibold">
                    Newest date pulled
                  </th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">
                    Symbols updated
                  </th>
                </tr>
              </thead>
              <tbody>
                {(store.data?.sync_log ?? []).map((row, index) => (
                  <tr key={index} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-1.5">{relativeTime(String(row.synced_at ?? ""))}</td>
                    <td className="px-4 py-1.5">
                      {date(String(row.most_recent_date_pulled ?? ""))}
                    </td>
                    <td className="tabular px-4 py-1.5 text-right">
                      {int(row.symbols_updated as number)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {store.data ? (
        <p className="text-2xs text-faint">
          Database: <code className="text-muted">{store.data.database_path}</code>
        </p>
      ) : null}
    </Page>
  );
}
