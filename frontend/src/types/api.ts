/** Shapes the backend actually returns. Kept narrow so a rename breaks the build. */

export type Row = Record<string, unknown>;

export interface ApiErrorBody {
  error: { code: string; message: string; detail?: string };
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Job {
  id: string;
  kind: string;
  label: string;
  status: JobStatus;
  progress: number;
  message: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  request: Record<string, unknown>;
}

export interface RunSummary {
  id: string;
  kind: string;
  created_at: string;
  finished_at: string | null;
  status: string;
  row_count: number;
  error: string | null;
  request: Record<string, unknown>;
}

export interface StrategyStat {
  strategy: string;
  signals: number;
  qualified: number;
}

export interface ScanStats {
  universe_size: number;
  loaded: number;
  usable: number;
  too_short: number;
  safety_gate_excluded: number;
  regime: string;
  regime_score: number;
  per_strategy: StrategyStat[];
  safety_gate_audit: Row[];
  ml_model: {
    ready: boolean;
    samples: number | null;
    min_samples: number | null;
    auc: number | null;
    brier: number | null;
    reason: string | null;
  } | null;
}

export interface RunResult {
  id: string;
  status: JobStatus | string;
  progress: number;
  message: string | null;
  error: string | null;
  request: Record<string, unknown>;
  rows: Row[];
  columns: string[];
  stats: Partial<ScanStats> & Record<string, unknown>;
  backtest?: Record<string, unknown> | null;
  trades?: Row[];
}

export interface FilteredResults {
  id: string;
  status: string;
  total: number;
  filtered: number;
  rows: Row[];
  columns: string[];
  stats: Partial<ScanStats> & Record<string, unknown>;
  confluence: Array<{
    Ticker: string;
    Strategies: string[];
    Count: number;
    "Best Score": number;
    Entry: number | null;
    Regime: string | null;
    Safety: string | null;
  }>;
}

export interface MarketStatus {
  exchange: string;
  segment: string;
  is_open: boolean;
  as_of: string;
  session_date: string | null;
  last_completed_session: string | null;
  open_time: string;
  close_time: string;
  timezone: string;
}

export interface Freshness {
  universe_size: number;
  latest: string | null;
  expected: string | null;
  current: boolean | null;
  days_behind: number | null;
  severity: "ok" | "error" | "unknown";
  message: string;
}

export interface ProviderStatus {
  dhan: { configured: boolean; auto_renew: boolean; token_issued_at: string | null };
  twelvedata: { configured: boolean };
  anthropic: { configured: boolean };
  github_backup: { configured: boolean };
}

export interface Overview {
  market: MarketStatus;
  data_store: { bars: number; symbols: number; latest_session: string | null };
  freshness: Freshness;
  forward: { summary: Row[]; totals: ForwardTotals };
  breadth: {
    window_days: number;
    by_strategy: Array<{ strategy: string; signals: number; at_gate: number; last_signal: string | null }>;
    daily: Array<{ date: string; signals: number }>;
  };
  top_opportunities: Row[];
  latest_scan: {
    id: string;
    created_at: string;
    status: string;
    row_count: number;
    universes: string[];
    strategies: number[];
  } | null;
  providers: ProviderStatus;
}

export interface ForwardTotals {
  total: number;
  open: number;
  closed: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  avg_r: number | null;
  total_r: number | null;
}

export interface Universe {
  name: string;
  source: string;
  requires_dhan: boolean;
  available: boolean;
  approx_size: number | null;
}

export interface PresetConfig {
  universes: string[];
  strategies: number[];
  min_score: number;
  use_live_prices: boolean;
  limit: number | null;
}

export interface Preset {
  id: number;
  name: string;
  description: string | null;
  builtin: boolean;
  config: PresetConfig;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
}

export interface WatchlistItem {
  id: number;
  watchlist_id: number;
  symbol: string;
  note: string | null;
  added_at: string;
  price?: number | null;
  price_source?: string;
  change_pct?: number | null;
  volume?: number | null;
  last_session?: string | null;
  signal_strategy?: string;
  signal_score?: number | null;
  signal_date?: string;
  signal_safety?: string;
}

export interface Watchlist {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  items: WatchlistItem[];
  count: number;
}

export interface Quote {
  symbol: string;
  name: string | null;
  security_id: string | number | null;
  exchange: string;
  segment: string;
  price: number;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  price_source: string;
  price_as_of: string | null;
  last_session: string | null;
  bars_stored: number;
  market_open: boolean;
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface History {
  symbol: string;
  timeframe: string;
  candles: Candle[];
  overlays: Record<string, Array<{ time: string; value: number | null }>>;
}

export interface Indicators {
  symbol: string;
  as_of: string;
  daily: Record<string, number | null>;
  weekly: Record<string, number | null>;
  monthly: Record<string, number | null>;
  range: Record<string, number | null>;
  compression: Record<string, unknown>;
}

export interface Condition {
  name: string;
  passed: boolean;
  distance_pct: number | null;
}

export interface StrategyConditions {
  strategy: string;
  label: string;
  signal: boolean;
  passed: number;
  total: number;
  conditions: Condition[];
}

export interface ConditionMatrix {
  symbol: string;
  as_of: string;
  strategies: StrategyConditions[];
}

export interface SafetyReport {
  symbol: string;
  score: number;
  status: string;
  flags: string[];
  base: { score: number; status: string; flags: string[] };
  metrics: { avg_traded_value_20d: number | null; news_risk: number | null };
  news: { available: boolean; items: Row[] };
  fundamentals_available: boolean;
}

export interface ForwardPositions {
  rows: Row[];
  meta: {
    live_symbols: number;
    as_of: string | null;
    source: string;
    market_open: boolean;
  };
}

export interface DataStore {
  database_path: string;
  bars: number;
  symbols: number;
  earliest_session: string | null;
  latest_session: string | null;
  thin_symbols: Array<{ symbol: string; bars: number; latest: string | null }>;
  sync_log: Row[];
  tail_days: number;
}

export interface BackupStatus {
  configured: boolean;
  repo: string | null;
  branch: string | null;
  db_path: string;
  db_rows: number;
  last_error: string;
}

export interface DatasetStatus {
  period: string;
  start: string;
  end: string;
  warmup_start: string;
  warmup_days: number;
  universe_size: number;
  ready: number;
  missing: number;
  local_bars: number;
  rows: Row[];
}

export interface BacktestStats {
  trades: number;
  by_strategy: Array<{
    strategy: string;
    trades: number;
    win_pct: number;
    avg_r: number;
    total_r: number;
    profit_factor: number;
    avg_return_pct: number;
    avg_mfe_pct: number;
    avg_mae_pct: number;
    best_score: number;
  }>;
  score_bands: Row[];
  elapsed_seconds?: number;
  learning_observations_added?: number;
}

export interface AppConfig {
  providers: ProviderStatus;
  universes: string[];
  strategies: Array<{ id: number; label: string; name: string }>;
  forward_gate_default: number;
  market: MarketStatus;
}
