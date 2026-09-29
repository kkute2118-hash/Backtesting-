"use client";

import { Activity } from "lucide-react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { date } from "@/lib/format";
import type { MarketBreadth } from "@/types/api";

/**
 * The market gate S1, S2, S3 and S6 wait on: the share of Nifty 500 stocks
 * closing at a 50-day high, summed over 10 sessions, against its 0.50 line.
 */
export function MarketBreadthCard({ breadth }: { breadth: MarketBreadth }) {
  const { latest, threshold, gate_open: open } = breadth;
  const top = Math.max(threshold * 1.3, ...breadth.history.map((h) => h.value));
  return (
    <Card id="market-breadth">
      <CardHeader
        title="Market breadth"
        description={`Share of ${breadth.universe} stocks at a 50-day high, summed over ${breadth.window} sessions.`}
        icon={<Activity className="h-3.5 w-3.5 text-accent" />}
        action={<Badge tone={open ? "up" : "warn"}>{open ? "Gate open" : "Waiting"}</Badge>}
      />
      <CardBody className="grid gap-3 p-3.5 md:grid-cols-[minmax(0,14rem)_1fr]">
        <div className="space-y-1.5">
          <div className="flex items-baseline gap-2">
            <span className={`tabular text-3xl font-semibold ${open ? "text-up" : "text-warn"}`}
              data-testid="breadth-value">
              {latest === null ? "—" : latest.toFixed(2)}
            </span>
            <span className="text-xs text-faint">needs {threshold.toFixed(2)}</span>
          </div>
          <p className="text-xs text-muted">
            {open
              ? `${breadth.gated_strategies.join(", ")} can signal.`
              : `${breadth.gated_strategies.join(", ")} are waiting. S4 and S5 trade at any breadth.`}
          </p>
          <p className="text-2xs text-faint">
            {breadth.as_of ? `As of ${date(breadth.as_of)}. ` : ""}
            {breadth.open_share_1y !== undefined
              ? `Open on ${Math.round(breadth.open_share_1y * 100)}% of sessions in the last year.`
              : ""}
          </p>
        </div>
        <div className="h-40 w-full" aria-label="Market breadth, recent sessions" role="img">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={breadth.history} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="hsl(var(--line))" strokeDasharray="2 4" vertical={false} />
              <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(5)}
                tick={{ fill: "hsl(var(--faint))", fontSize: 10 }} tickLine={false}
                axisLine={{ stroke: "hsl(var(--line))" }} minTickGap={28} />
              <YAxis domain={[0, Math.ceil(top * 10) / 10]} tickCount={4}
                tickFormatter={(v: number) => v.toFixed(1)}
                tick={{ fill: "hsl(var(--faint))", fontSize: 10 }} axisLine={false} tickLine={false}
                width={34} />
              <ReferenceLine y={threshold} stroke="hsl(var(--warn))" strokeDasharray="4 3"
                label={{ value: threshold.toFixed(2), position: "insideTopRight",
                         fill: "hsl(var(--warn))", fontSize: 10 }} />
              <Tooltip
                contentStyle={{ background: "hsl(var(--surface))", border: "1px solid hsl(var(--line))",
                                borderRadius: 6, fontSize: 11 }}
                labelFormatter={(v) => date(String(v))}
                formatter={(v) => [Number(v).toFixed(2), "Breadth"]}
              />
              <Line type="monotone" dataKey="value" stroke="hsl(var(--accent))" strokeWidth={2}
                dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardBody>
    </Card>
  );
}
