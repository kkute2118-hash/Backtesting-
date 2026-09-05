"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  AppConfig, BackupStatus, ConditionMatrix, DataStore, DatasetStatus,
  FilteredResults, ForwardPositions, Freshness, History, Indicators, Job,
  Overview, Preset, PresetConfig, Quote, Row, RunResult, RunSummary,
  SafetyReport, Universe, Watchlist,
} from "@/types/api";

/** Poll intervals, in one place so cadence is a deliberate decision.
 *  Live quotes move constantly; a universe list changes once a day. */
export const REFRESH = {
  live: 15_000,
  market: 60_000,
  slow: 5 * 60_000,
  job: 900,
} as const;

type Options<T> = Omit<UseQueryOptions<T, Error, T, readonly unknown[]>, "queryKey" | "queryFn">;

// --------------------------------------------------------------------------- //
// reference data
// --------------------------------------------------------------------------- //
export const useConfig = () =>
  useQuery({
    queryKey: ["config"],
    queryFn: () => api.get<AppConfig>("/config"),
    staleTime: REFRESH.slow,
  });

export const useUniverses = () =>
  useQuery({
    queryKey: ["universes"],
    queryFn: async () => (await api.get<{ universes: Universe[] }>("/universes")).universes,
    staleTime: REFRESH.slow,
  });

export const useOverview = () =>
  useQuery({
    queryKey: ["overview"],
    queryFn: () => api.get<Overview>("/market/overview"),
    refetchInterval: REFRESH.market,
  });

export const useFreshness = (universes: string[]) =>
  useQuery({
    queryKey: ["freshness", universes],
    queryFn: () => api.get<Freshness>("/market/freshness", { universes }),
    enabled: universes.length > 0,
    refetchInterval: REFRESH.market,
  });

// --------------------------------------------------------------------------- //
// jobs
// --------------------------------------------------------------------------- //
/**
 * Follow one job to completion.
 *
 * Polling stops the moment the job reaches a terminal state — a finished scan
 * must not keep a timer alive for as long as the tab is open.
 */
export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<Job>(`/jobs/${jobId}`),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? REFRESH.job : false;
    },
  });
}

export const useCancelJob = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.post<Job>(`/jobs/${jobId}/cancel`),
    onSuccess: (job) => client.setQueryData(["job", job.id], job),
  });
};

// --------------------------------------------------------------------------- //
// scanner
// --------------------------------------------------------------------------- //
export interface ScanRequest {
  universes: string[];
  strategies: number[];
  min_score: number;
  use_live_prices: boolean;
  limit?: number | null;
  preset_id?: number | null;
}

export const useStartScan = () =>
  useMutation({ mutationFn: (payload: ScanRequest) => api.post<Job>("/scanner/runs", payload) });

export const useScanRuns = (limit = 25) =>
  useQuery({
    queryKey: ["scan-runs", limit],
    queryFn: () => api.get<RunSummary[]>("/scanner/runs", { limit }),
  });

export const useRun = (runId: string | null, enabled = true) =>
  useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.get<RunResult>(`/scanner/runs/${runId}`),
    enabled: Boolean(runId) && enabled,
  });

export interface ResultFilters {
  search?: string;
  strategies?: string[];
  safety_status?: string[];
  min_score?: number | null;
  max_score?: number | null;
  min_rsi?: number | null;
  max_rsi?: number | null;
  min_relvol?: number | null;
  max_relvol?: number | null;
  min_price?: number | null;
  max_price?: number | null;
  min_win_probability?: number | null;
  min_safety?: number | null;
  min_htf?: number | null;
  min_footprint?: number | null;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  offset?: number;
  limit?: number;
}

export const useFilteredResults = (runId: string | null, filters: ResultFilters,
                                   enabled = true) =>
  useQuery({
    queryKey: ["run-results", runId, filters],
    queryFn: () => api.post<FilteredResults>(`/scanner/runs/${runId}/results`, filters),
    enabled: Boolean(runId) && enabled,
    placeholderData: (previous) => previous,
  });

export const useValidateDsl = () =>
  useMutation({
    mutationFn: (rules: string) =>
      api.post<{
        valid: boolean;
        conditions: Array<{ text: string; column: string; operator: string }>;
        errors: string[];
        columns: string[];
        operators: string[];
      }>("/scanner/custom/validate", { rules }),
  });

export const useStartCustomScan = () =>
  useMutation({
    mutationFn: (payload: {
      universes: string[]; rules: string; backtest: boolean;
      sl_pct: number; target_r: number;
    }) => api.post<Job>("/scanner/custom", payload),
  });

export const useStartSepaScan = () =>
  useMutation({
    mutationFn: (payload: {
      universes: string[]; min_score: number; max_stocks: number | null;
      apply_fundamental_screen: boolean;
    }) => api.post<Job>("/scanner/sepa", payload),
  });

export const useStartRadar = () =>
  useMutation({
    mutationFn: (payload: {
      universes: string[]; strategies: number[]; max_missing: number; min_readiness: number;
    }) => api.post<Job>("/radar/runs", payload),
  });

export const useRadarRuns = (limit = 25) =>
  useQuery({
    queryKey: ["radar-runs", limit],
    queryFn: () => api.get<RunSummary[]>("/radar/runs", { limit }),
  });

// --------------------------------------------------------------------------- //
// stocks
// --------------------------------------------------------------------------- //
export const useQuote = (symbol: string, live = true, options?: Options<Quote>) =>
  useQuery({
    queryKey: ["quote", symbol, live],
    queryFn: () => api.get<Quote>(`/stocks/${symbol}`, { live }),
    refetchInterval: live ? REFRESH.live : false,
    ...options,
  });

export const useHistory = (symbol: string, timeframe: string) =>
  useQuery({
    queryKey: ["history", symbol, timeframe],
    queryFn: () => api.get<History>(`/stocks/${symbol}/history`, { timeframe }),
    staleTime: REFRESH.slow,
  });

export const useIndicators = (symbol: string) =>
  useQuery({
    queryKey: ["indicators", symbol],
    queryFn: () => api.get<Indicators>(`/stocks/${symbol}/indicators`),
  });

export const useConditions = (symbol: string) =>
  useQuery({
    queryKey: ["conditions", symbol],
    queryFn: () => api.get<ConditionMatrix>(`/stocks/${symbol}/conditions`),
  });

export const useStockSignals = (symbol: string) =>
  useQuery({
    queryKey: ["stock-signals", symbol],
    queryFn: () => api.get<{ signals: Row[]; forward_tests: Row[] }>(`/stocks/${symbol}/signals`),
  });

export const useSafety = (symbol: string, news = false) =>
  useQuery({
    queryKey: ["safety", symbol, news],
    queryFn: () => api.get<SafetyReport>(`/stocks/${symbol}/safety`, { news }),
  });

export const useStockSearch = (term: string) =>
  useQuery({
    queryKey: ["stock-search", term],
    queryFn: () =>
      api.get<{ results: Array<{ symbol: string; bars: number; latest: string | null }> }>(
        "/stocks/search", { q: term, limit: 12 }),
    enabled: term.trim().length >= 1,
    staleTime: 30_000,
  });

// --------------------------------------------------------------------------- //
// forward tests
// --------------------------------------------------------------------------- //
export const useForwardPositions = (live = true) =>
  useQuery({
    queryKey: ["forward-positions", live],
    queryFn: () => api.get<ForwardPositions>("/forward/positions", { live }),
    refetchInterval: live ? REFRESH.live : false,
  });

export const useForwardSummary = () =>
  useQuery({
    queryKey: ["forward-summary"],
    queryFn: () => api.get<{ rows: Row[]; totals: Overview["forward"]["totals"] }>("/forward/summary"),
  });

export const useForwardResults = () =>
  useQuery({
    queryKey: ["forward-results"],
    queryFn: () => api.get<{ rows: Row[] }>("/forward/results"),
  });

export const useScannerSignals = () =>
  useQuery({
    queryKey: ["scanner-signals"],
    queryFn: () => api.get<{ rows: Row[] }>("/scanner/signals"),
  });

export const useRefreshForward = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ checked: number; closed: number }>("/forward/refresh"),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["forward-positions"] });
      client.invalidateQueries({ queryKey: ["forward-summary"] });
      client.invalidateQueries({ queryKey: ["overview"] });
    },
  });
};

export const useAddForwardCandidates = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (rows: Row[]) =>
      api.post<{ added: number; submitted: number }>("/forward/candidates", { rows }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["forward-positions"] });
      client.invalidateQueries({ queryKey: ["forward-summary"] });
    },
  });
};

// --------------------------------------------------------------------------- //
// watchlists
// --------------------------------------------------------------------------- //
export const useWatchlists = (quotes = true) =>
  useQuery({
    queryKey: ["watchlists", quotes],
    queryFn: async () =>
      (await api.get<{ watchlists: Watchlist[] }>("/watchlists", { quotes })).watchlists,
    refetchInterval: quotes ? REFRESH.market : false,
  });

function invalidateWatchlists(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: ["watchlists"] });
}

export const useCreateWatchlist = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; description?: string }) =>
      api.post<Watchlist>("/watchlists", payload),
    onSuccess: () => invalidateWatchlists(client),
  });
};

export const useDeleteWatchlist = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/watchlists/${id}`),
    onSuccess: () => invalidateWatchlists(client),
  });
};

export const useAddToWatchlist = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, symbols }: { id: number; symbols: string[] }) =>
      api.post<Watchlist>(`/watchlists/${id}/symbols`, { symbols }),
    onSuccess: () => invalidateWatchlists(client),
  });
};

export const useRemoveFromWatchlist = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, symbol }: { id: number; symbol: string }) =>
      api.delete<Watchlist>(`/watchlists/${id}/symbols/${symbol}`),
    onSuccess: () => invalidateWatchlists(client),
  });
};

// --------------------------------------------------------------------------- //
// presets
// --------------------------------------------------------------------------- //
export const usePresets = () =>
  useQuery({
    queryKey: ["presets"],
    queryFn: async () => (await api.get<{ presets: Preset[] }>("/presets")).presets,
  });

export const useCreatePreset = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; description?: string; config: PresetConfig }) =>
      api.post<Preset>("/presets", payload),
    onSuccess: () => client.invalidateQueries({ queryKey: ["presets"] }),
  });
};

export const useUpdatePreset = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: number; name?: string;
      description?: string; config?: PresetConfig }) =>
      api.patch<Preset>(`/presets/${id}`, payload),
    onSuccess: () => client.invalidateQueries({ queryKey: ["presets"] }),
  });
};

export const useDeletePreset = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/presets/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["presets"] }),
  });
};

// --------------------------------------------------------------------------- //
// learning
// --------------------------------------------------------------------------- //
export const useLearningEdge = () =>
  useQuery({ queryKey: ["learning-edge"], queryFn: () => api.get<{ rows: Row[] }>("/learning/edge") });

export const useLearningSnapshot = () =>
  useQuery({
    queryKey: ["learning-snapshot"],
    queryFn: () => api.get<{ total: number; rows: Row[]; columns: string[] }>("/learning/snapshot"),
  });

export const useLearningComponents = () =>
  useQuery({
    queryKey: ["learning-components"],
    queryFn: () => api.get<{ rows: Row[] }>("/learning/components"),
  });

export const useLearningModel = () =>
  useQuery({
    queryKey: ["learning-model"],
    queryFn: () => api.get<{
      ready: boolean; samples: number | null; min_samples: number | null;
      reason: string | null; gbc_auc: number | null; gbc_brier: number | null;
    }>("/learning/model"),
  });

export const useLearningDatabase = () =>
  useQuery({
    queryKey: ["learning-database"],
    queryFn: () => api.get<{
      database: string;
      total_rows: number;
      tables: Array<{ table: string; rows: number; rebuildable: boolean }>;
    }>("/learning/database"),
  });

export const useCoach = (strategy: string) =>
  useQuery({
    queryKey: ["coach", strategy],
    queryFn: () => api.get<Record<string, unknown>>("/learning/coach", { strategy }),
  });

// --------------------------------------------------------------------------- //
// backtest
// --------------------------------------------------------------------------- //
export const useDatasetStatus = (universes: string[], period: string) =>
  useQuery({
    queryKey: ["backtest-dataset", universes, period],
    queryFn: () => api.get<DatasetStatus>("/backtest/dataset", { universes, period }),
    enabled: universes.length > 0,
  });

export const useLatestBacktest = () =>
  useQuery({
    queryKey: ["backtest-latest"],
    queryFn: () => api.get<{
      available: boolean; rows: Row[]; columns: string[];
      stats: Record<string, unknown>; run: unknown[] | null;
    }>("/backtest/latest"),
  });

export const useStartBacktest = () =>
  useMutation({
    mutationFn: (payload: { universes: string[]; period: string; threshold: number }) =>
      api.post<Job>("/backtest/runs", payload),
  });

export const useStartStudy = (kind: "raw-signals" | "sl-calibration" | "s4-extension" | "s4-recovery") =>
  useMutation({
    mutationFn: (payload: { universes: string[]; period: string }) =>
      api.post<Job>(`/backtest/${kind}`, payload),
  });

export const usePortfolio = () =>
  useMutation({
    mutationFn: (payload: { rows: Row[]; capital: number; risk_pct: number; slots: number }) =>
      api.post<Record<string, number | string>>("/backtest/portfolio", payload),
  });

// --------------------------------------------------------------------------- //
// data manager
// --------------------------------------------------------------------------- //
export const useDataStore = () =>
  useQuery({ queryKey: ["data-store"], queryFn: () => api.get<DataStore>("/data/store") });

export const useBackupStatus = () =>
  useQuery({ queryKey: ["backup-status"], queryFn: () => api.get<BackupStatus>("/data/backup") });

export const useSyncLatest = () =>
  useMutation({
    mutationFn: (payload: { universes: string[] }) =>
      api.post<Job>("/data/sync/latest", payload),
  });

export const useSyncFull = () =>
  useMutation({
    mutationFn: (payload: { universes: string[]; period: string }) =>
      api.post<Job>("/data/sync/full", payload),
  });

export const useRunDiagnostics = () =>
  useMutation({
    mutationFn: (payload: { universes: string[] }) => api.post<Job>("/data/diagnostics", payload),
  });

export const useStoredDiagnostics = () =>
  useQuery({
    queryKey: ["stored-diagnostics"],
    queryFn: () => api.get<{ rows: Row[] }>("/data/diagnostics"),
  });

export const useConnectionTest = () =>
  useMutation({ mutationFn: () => api.get<{ checks: unknown }>("/data/connection-test") });

/** Refresh whatever the backup and token actions can have changed. */
function useBackupInvalidation() {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: ["backup-status"] });
    client.invalidateQueries({ queryKey: ["config"] });
  };
}

export const useRunBackup = () => {
  const invalidate = useBackupInvalidation();
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>("/data/backup"),
    onSuccess: invalidate,
  });
};

export const useRestoreBackup = () => {
  const invalidate = useBackupInvalidation();
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>("/data/backup/restore"),
    onSuccess: invalidate,
  });
};

/** Checks the whole backup path without writing a commit, and names the failure. */
export const useBackupDiagnostic = () =>
  useMutation({ mutationFn: () => api.get<{ result: unknown }>("/data/backup/diagnostic") });

export const useRenewToken = () => {
  const invalidate = useBackupInvalidation();
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean; issued_at: string }>("/data/token/renew"),
    onSuccess: invalidate,
  });
};

// --------------------------------------------------------------------------- //
// preferences
// --------------------------------------------------------------------------- //
export const usePreferences = () =>
  useQuery({
    queryKey: ["preferences"],
    queryFn: async () =>
      (await api.get<{ preferences: Record<string, unknown> }>("/preferences")).preferences,
    staleTime: REFRESH.slow,
  });

export const useSetPreference = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: { key: string; value: unknown }) =>
      api.put<{ preferences: Record<string, unknown> }>("/preferences", payload),
    onSuccess: () => client.invalidateQueries({ queryKey: ["preferences"] }),
  });
};
