"use client";

import { Dna, Landmark } from "lucide-react";

import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Note } from "@/components/ui/Misc";
import { EmptyState, Skeleton } from "@/components/ui/States";
import { useFundamentals, useStockDna } from "@/hooks/queries";
import { inrCompact, num } from "@/lib/format";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <dt className="text-2xs text-muted">{label}</dt>
      <dd className="tabular text-xs font-medium text-ink">{value}</dd>
    </div>
  );
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : num(value, 2);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/**
 * Stock DNA: the stock's own historical leg size.
 *
 * This is what the SEPA position-size multiplier is derived from — a stock that
 * historically moves 12% per leg is not the same trade as one that moves 40%,
 * and sizing them identically is how a portfolio ends up concentrated by
 * accident.
 */
export function StockDnaCard({ symbol }: { symbol: string }) {
  const { data, isLoading, error } = useStockDna(symbol);

  return (
    <Card>
      <CardHeader
        title="Stock DNA"
        description="This stock's own historical behaviour, measured over the last three years."
        icon={<Dna className="h-3.5 w-3.5 text-accent" />}
      />
      {isLoading ? (
        <Skeleton className="m-4 h-32" />
      ) : error || !data ? (
        <EmptyState title="Not enough history"
          message="The DNA measure needs a multi-year record for this stock." />
      ) : (
        <CardBody className="pt-2">
          <dl className="divide-y divide-line/60">
            {Object.entries(data)
              .filter(([key]) => key !== "symbol")
              .map(([key, value]) => (
                <Row
                  key={key}
                  label={key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                  value={display(value)}
                />
              ))}
          </dl>
        </CardBody>
      )}
    </Card>
  );
}

/**
 * Fundamentals, only when Twelve Data is configured.
 *
 * Kept off the main scan path on purpose: this is one request per symbol, and
 * running it across a whole universe would make a market-wide scan unusable.
 */
export function FundamentalsCard({
  symbol,
  available,
}: {
  symbol: string;
  available: boolean;
}) {
  const { data, isLoading } = useFundamentals(symbol, available);

  if (!available) {
    return (
      <Card>
        <CardHeader title="Fundamentals"
          icon={<Landmark className="h-3.5 w-3.5 text-accent" />} />
        <CardBody>
          <Note>
            Fundamentals come from Twelve Data, which is not configured. Set
            TWELVEDATA_API_KEY in the backend environment to enable them. Everything else on
            this page works without it.
          </Note>
        </CardBody>
      </Card>
    );
  }

  const profile = data?.profile ?? {};
  const interesting = ["marketCapitalization", "sector", "industry", "peRatio",
    "debtToEquity", "returnOnEquity", "revenueGrowth", "heldPercentInsiders"];
  const shown = interesting.filter((key) => key in profile);

  return (
    <Card>
      <CardHeader
        title="Fundamentals"
        description="Enrichment for a shortlisted candidate, never for a whole scan."
        icon={<Landmark className="h-3.5 w-3.5 text-accent" />}
      />
      {isLoading ? (
        <Skeleton className="m-4 h-32" />
      ) : !data?.available ? (
        <EmptyState title="Unavailable" message={data?.message} />
      ) : shown.length === 0 && data.piotroski === null ? (
        <EmptyState title="No fundamentals returned"
          message={`Twelve Data has no filing data for ${symbol}.`} />
      ) : (
        <CardBody className="space-y-3 pt-2">
          <dl className="divide-y divide-line/60">
            {data.piotroski !== null && data.piotroski !== undefined ? (
              <Row label="Piotroski F-score" value={`${display(data.piotroski)} / 9`} />
            ) : null}
            {shown.map((key) => (
              <Row
                key={key}
                label={key.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase())}
                value={key === "marketCapitalization"
                  ? inrCompact(Number(profile[key]))
                  : display(profile[key])}
              />
            ))}
          </dl>
          {data.flags.length > 0 ? (
            <ul className="space-y-1">
              {data.flags.map((flag) => (
                <li key={flag}
                  className="rounded-md border border-warn/25 bg-warn-soft/30 px-2.5 py-1.5
                    text-2xs text-ink">
                  {flag}
                </li>
              ))}
            </ul>
          ) : null}
          <Note>
            Fundamentals are a risk layer, not a signal. They can downgrade a candidate; they
            never create one.
          </Note>
        </CardBody>
      )}
    </Card>
  );
}
