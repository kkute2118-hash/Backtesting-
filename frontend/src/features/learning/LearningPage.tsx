"use client";

import { Brain, Database, GraduationCap, TrendingUp } from "lucide-react";
import { useState } from "react";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Select } from "@/components/ui/Inputs";
import { Note, Stat } from "@/components/ui/Misc";
import { EmptyState, ErrorState, Skeleton, SkeletonCards } from "@/components/ui/States";
import {
  useCoach, useLearningComponents, useLearningDatabase, useLearningEdge, useLearningModel,
  useLearningSnapshot,
} from "@/hooks/queries";
import { compact, int, num, pct, signed } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Row } from "@/types/api";

function n(row: Row, key: string): number | null {
  const value = row[key];
  return typeof value === "number" ? value : null;
}
function s(row: Row, key: string): string {
  const value = row[key];
  return value === null || value === undefined ? "" : String(value);
}

/** A table rendered straight from an engine DataFrame, columns and all. */
function FrameTable({
  rows,
  columns,
  emptyTitle,
  emptyMessage,
  maxHeight = "24rem",
}: {
  rows: Row[];
  columns?: string[];
  emptyTitle: string;
  emptyMessage?: string;
  maxHeight?: string;
}) {
  const keys = columns && columns.length > 0
    ? columns
    : rows.length > 0 ? Object.keys(rows[0]) : [];

  if (rows.length === 0) {
    return <EmptyState title={emptyTitle} message={emptyMessage} />;
  }

  return (
    <div className="overflow-auto scroll-thin" style={{ maxHeight }}>
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
            {keys.map((key) => (
              <th key={key} scope="col"
                className={cn("whitespace-nowrap px-3 py-2 font-semibold",
                  typeof rows[0]?.[key] === "number" ? "text-right" : "text-left")}>
                {key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-b border-line/60 last:border-0">
              {keys.map((key) => {
                const value = row[key];
                const isNumber = typeof value === "number";
                return (
                  <td key={key}
                    className={cn("whitespace-nowrap px-3 py-1.5",
                      isNumber ? "tabular text-right" : "text-left")}>
                    {value === null || value === undefined
                      ? <span className="text-faint">—</span>
                      : isNumber ? num(value, Number.isInteger(value) ? 0 : 3) : String(value)}
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

export function LearningPage() {
  const [strategy, setStrategy] = useState("S1");

  const edge = useLearningEdge();
  const snapshot = useLearningSnapshot();
  const components = useLearningComponents();
  const model = useLearningModel();
  const database = useLearningDatabase();
  const coach = useCoach(strategy);

  const observations = snapshot.data?.total ?? 0;

  return (
    <Page>
      <PageHeader
        title="Adaptive learning"
        description="What kinds of valid setup historically produced better outcomes. None of
          this changes strategy qualification — the rules stay authoritative, and learning only
          affects how survivors are ranked."
      />

      {model.isLoading ? (
        <SkeletonCards count={3} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat label="Learning observations" value={int(observations)}
            sub="Completed trades with a recorded outcome"
            icon={<Brain className="h-3.5 w-3.5" />} />
          <Stat
            label="Win-probability model"
            value={model.data?.ready ? "Trained" : "Not ready"}
            tone={model.data?.ready ? "up" : "warn"}
            sub={
              model.data?.ready
                ? `${int(model.data.samples)} samples · held-out AUC ${num(model.data.gbc_auc, 3)}`
                : model.data?.reason ??
                  `${int(model.data?.samples)} of ${int(model.data?.min_samples)} needed`
            }
          />
          <Stat label="Score bands measured" value={int((edge.data?.rows ?? []).length)}
            sub="Strategy × score band with enough evidence to report" />
          <Stat label="Database rows" value={compact(database.data?.total_rows)}
            sub={`${int((database.data?.tables ?? []).length)} tables`}
            icon={<Database className="h-3.5 w-3.5" />} />
        </div>
      )}

      {observations === 0 ? (
        <Card>
          <EmptyState
            icon={<Brain className="h-6 w-6" />}
            title="No learning evidence yet"
            message="Learning observations come from resolved trades — run a walk-forward
              backtest, or let recorded forward tests reach their stop or target. Until then
              every ranking here falls back to the raw score."
          />
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader
            title="Score-band edge"
            description="Win rate and average R per strategy and score band, shrunk toward
              neutral so a three-trade sample cannot look like an edge."
            icon={<TrendingUp className="h-3.5 w-3.5 text-accent" />}
          />
          {edge.isLoading ? (
            <Skeleton className="m-4 h-48" />
          ) : edge.error ? (
            <ErrorState error={edge.error} compact />
          ) : (
            <FrameTable
              rows={edge.data?.rows ?? []}
              emptyTitle="No score bands measured yet"
              emptyMessage="A band needs at least 20 resolved trades before it is reported."
            />
          )}
        </Card>

        <Card>
          <CardHeader
            title="Component weights"
            description="Which score components separated winners from losers. Components with
              too little evidence keep a neutral weight of 1.0."
          />
          {components.isLoading ? (
            <Skeleton className="m-4 h-48" />
          ) : (
            <FrameTable
              rows={components.data?.rows ?? []}
              emptyTitle="No component evidence yet"
              emptyMessage="Each component needs at least five trades either side of its median."
            />
          )}
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Strategy coach"
          description="A read-only statistical breakdown per strategy — regimes, components and
            decision-tree rules learned from resolved trades. No language model involved."
          icon={<GraduationCap className="h-3.5 w-3.5 text-accent" />}
          action={
            <Select value={strategy} onChange={(event) => setStrategy(event.target.value)}
              aria-label="Strategy" className="h-8 w-32">
              {["S1", "S2", "S3", "S4_SEPA"].map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </Select>
          }
        />
        <CardBody>
          {coach.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : !coach.data?.available ? (
            <EmptyState
              title={`No resolved trades for ${strategy}`}
              message="The coach needs completed observations for this strategy before it can
                say anything worth reading."
            />
          ) : (
            <CoachReport report={coach.data} />
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Learning database"
          description="Every observation recorded, and which tables are rebuildable versus
            irreplaceable."
        />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap gap-1.5">
            {(database.data?.tables ?? [])
              .filter((table) => table.rows > 0)
              .sort((a, b) => b.rows - a.rows)
              .slice(0, 18)
              .map((table) => (
                <span key={table.table}
                  className="flex items-center gap-1.5 rounded-md border border-line bg-elevated
                    px-2 py-1 text-2xs">
                  <span className="font-medium text-ink">{table.table}</span>
                  <span className="tabular text-faint">{compact(table.rows)}</span>
                  {table.rebuildable ? (
                    <Badge tone="neutral">rebuildable</Badge>
                  ) : (
                    <Badge tone="accent">backed up</Badge>
                  )}
                </span>
              ))}
          </div>
          <Note>
            Tables marked <strong>backed up</strong> cannot be reproduced from anywhere — forward
            tests, resolved outcomes and accumulated learning. They are what the GitHub backup
            protects. Candles are rebuildable from Dhan in one sync.
          </Note>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Raw observations"
          description={`${int(observations)} recorded trades with their outcome and score
            components.`} />
        {snapshot.isLoading ? (
          <Skeleton className="m-4 h-40" />
        ) : (
          <FrameTable
            rows={(snapshot.data?.rows ?? []).slice(0, 200)}
            columns={snapshot.data?.columns}
            emptyTitle="No observations recorded"
            maxHeight="28rem"
          />
        )}
      </Card>
    </Page>
  );
}

function CoachReport({ report }: { report: Record<string, unknown> }) {
  const samples = report.n_samples as number | null;
  const enough = report.enough_for_breakdown as boolean;
  const winRate = report.overall_win_rate as number | null;
  const avgR = report.overall_avg_r as number | null;
  const regimes = (report.regime_breakdown ?? []) as Row[];
  const componentRows = (report.component_breakdown ?? []) as Row[];
  const rules = report.tree_rules;
  const note = report.tree_note as string | null;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Resolved trades" value={int(samples)} />
        <Stat label="Win rate" value={winRate === null ? "—" : pct(winRate, 1)}
          tone={winRate !== null && winRate >= 50 ? "up" : "down"} />
        <Stat label="Average R" value={signed(avgR, 3)}
          tone={(avgR ?? 0) > 0 ? "up" : "down"} />
      </div>

      {!enough ? (
        <Note>
          The breakdowns below need a larger sample before they are reported. What is shown is the
          overall record only.
        </Note>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-faint">
              By market regime
            </p>
            <FrameTable rows={regimes} emptyTitle="No regime breakdown" maxHeight="16rem" />
          </div>
          <div>
            <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-faint">
              By score component
            </p>
            <FrameTable rows={componentRows} emptyTitle="No component breakdown"
              maxHeight="16rem" />
          </div>
        </div>
      )}

      {Array.isArray(rules) && rules.length > 0 ? (
        <div>
          <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-faint">
            Learned rules
          </p>
          <ul className="space-y-1">
            {(rules as unknown[]).map((rule, index) => (
              <li key={index}
                className="rounded-md border border-line bg-elevated px-2.5 py-1.5 text-xs
                  text-muted">
                {typeof rule === "string" ? rule : JSON.stringify(rule)}
              </li>
            ))}
          </ul>
          {note ? <p className="mt-1.5 text-2xs text-faint">{note}</p> : null}
        </div>
      ) : note ? (
        <Note>{note}</Note>
      ) : null}
    </div>
  );
}
