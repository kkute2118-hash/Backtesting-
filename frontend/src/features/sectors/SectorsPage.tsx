"use client";

import { Download, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Banner, Note } from "@/components/ui/Misc";
import { EmptyState, ErrorState, SkeletonTable } from "@/components/ui/States";
import { useSectorStrength, useSyncIndices, useSyncSectors } from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { num as fmtNum } from "@/lib/format";
import type { Row } from "@/types/api";

/**
 * Which sectors are leading, so a scan can be narrowed to one.
 *
 * Three windows rather than one, on purpose: a sector leading over a month and
 * lagging over six is a different proposition from one leading over both, and
 * a single "strength" number hides exactly that. The table sorts by the
 * shortest window but shows all three so the disagreement stays visible.
 *
 * The "Measured from" column is not decoration. Sector membership needs one
 * fetch of the NSE constituent lists; index PRICES need Dhan. With membership
 * alone, a sector's return is an equal-weighted composite of its members in
 * the local candle store — usable, but not the index, and the column says
 * which one you are reading.
 */
function number(row: Row, key: string): number | null {
  const v = row[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function Delta({ value }: { value: number | null }) {
  if (value === null) return <span className="text-faint">—</span>;
  return (
    <span className={value > 0 ? "text-up" : value < 0 ? "text-down" : undefined}>
      {value > 0 ? "+" : ""}{fmtNum(value, 2)}%
    </span>
  );
}

export function SectorsPage() {
  const { data, isLoading, error, refetch } = useSectorStrength();
  const syncSectors = useSyncSectors();
  const syncIndices = useSyncIndices();

  const lookbacks = data?.lookbacks ?? [21, 63, 126];
  const benchmark = data?.benchmark ?? "NIFTY 500";

  const columns: Column<Row>[] = [
    {
      key: "Sector", header: "Sector", align: "left", sticky: true, sortable: true,
      render: (r) => <span className="font-medium text-ink">{String(r.Sector ?? "")}</span>,
      value: (r) => String(r.Sector ?? ""),
    },
    {
      key: "Members", header: "Members", align: "right", sortable: true,
      render: (r) => fmtNum(number(r, "Members"), 0),
      value: (r) => number(r, "Members"),
    },
    ...lookbacks.map<Column<Row>>((n) => ({
      key: `Return ${n}d %`,
      header: `${n}d`,
      align: "right",
      sortable: true,
      description: `Sector return over the last ${n} trading days`,
      render: (r) => <Delta value={number(r, `Return ${n}d %`)} />,
      value: (r) => number(r, `Return ${n}d %`),
    })),
    ...lookbacks.map<Column<Row>>((n) => ({
      key: `vs ${benchmark} ${n}d`,
      header: `vs ${benchmark} ${n}d`,
      align: "right",
      sortable: true,
      description: `Outperformance against ${benchmark} over ${n} days`,
      render: (r) => <Delta value={number(r, `vs ${benchmark} ${n}d`)} />,
      value: (r) => number(r, `vs ${benchmark} ${n}d`),
    })),
    {
      key: "Source", header: "Measured from", align: "left",
      render: (r) => (
        <Badge tone={String(r.Source) === "index" ? "accent" : "neutral"}>
          {String(r.Source ?? "")}
        </Badge>
      ),
      value: (r) => String(r.Source ?? ""),
    },
  ];

  const onSyncSectors = async () => {
    try {
      const res = await syncSectors.mutateAsync();
      const failed = Object.keys(res.failed ?? {}).length;
      toast.success(
        `Mapped ${res.symbols_mapped} symbols across ${res.synced.length} sectors` +
          (failed ? ` — ${failed} list(s) failed` : ""),
      );
      refetch();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  const onSyncIndices = async () => {
    try {
      const res = await syncIndices.mutateAsync(5);
      const ok = Object.keys(res.synced ?? {}).length;
      const failed = Object.keys(res.failed ?? {}).length;
      toast.success(`Stored ${ok} index histories` + (failed ? `, ${failed} failed` : ""));
      refetch();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  return (
    <Page>
      <PageHeader
        title="Sector strength"
        description="Which sectors are outperforming, over three windows — so a scan can be narrowed to the leaders."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button onClick={onSyncSectors} loading={syncSectors.isPending}>
              <Download className="mr-1.5 h-4 w-4" aria-hidden /> Sync sector lists
            </Button>
            <Button onClick={onSyncIndices} loading={syncIndices.isPending}>
              <RefreshCw className="mr-1.5 h-4 w-4" aria-hidden /> Sync index prices
            </Button>
          </div>
        }
      />

      {error ? <ErrorState error={error} onRetry={() => void refetch()} /> : null}

      {data?.note ? (
        <Banner tone="warn" title="Composite, not index">{data.note}</Banner>
      ) : null}

      <Card>
        <CardHeader
          title="Sector ranking"
          description={
            data?.as_of
              ? `As of ${data.as_of} · ${data.symbols_mapped ?? 0} symbols mapped · sorted by the ${lookbacks[0]}-day window`
              : "Sorted by the shortest window"
          }
        />
        <CardBody>
          {isLoading ? (
            <SkeletonTable rows={8} cols={7} />
          ) : data && !data.ready ? (
            <EmptyState
              title="No sector data yet"
              message={data.reason ?? "Sync the sector lists to get started."}
              action={<Button onClick={onSyncSectors} loading={syncSectors.isPending}>
                Sync sector lists
              </Button>}
            />
          ) : data?.sectors?.length ? (
            <>
              <DataTable
                rows={data.sectors}
                columns={columns}
                getRowId={(r) => String(r.Sector ?? Math.random())}
              />
              <Note className="mt-3">
                A sector leading on {lookbacks[0]} days but lagging on {lookbacks[2]} is rotating
                in, not established — check all three before narrowing a scan. None of this has
                been tested as a filter against the trade record yet.
              </Note>
            </>
          ) : (
            <EmptyState title="Nothing to rank" message="Sync the sector lists first." />
          )}
        </CardBody>
      </Card>
    </Page>
  );
}
