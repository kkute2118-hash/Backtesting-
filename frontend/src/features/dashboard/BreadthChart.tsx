"use client";

import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { EmptyState } from "@/components/ui/States";
import { date } from "@/lib/format";

/**
 * Signals per day over the recent window.
 *
 * This is genuine breadth from the scanner's own record — how often the rules
 * are finding anything — not an advance/decline line. The engine never computes
 * A/D, so this does not pretend to show one.
 */
export function BreadthChart({
  data,
  windowDays,
}: {
  data: Array<{ date: string; signals: number }>;
  windowDays: number;
}) {
  if (data.length === 0) {
    return (
      <EmptyState
        title="No recorded signals yet"
        message={`Nothing has qualified in the last ${windowDays} days. Run a scan to start
          building the record.`}
      />
    );
  }

  return (
    <div className="h-52 w-full px-1 pb-1">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 8, bottom: 4, left: -18 }}>
          <defs>
            <linearGradient id="breadth" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.35} />
              <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="hsl(var(--line))" strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={(value: string) => value.slice(5)}
            tick={{ fill: "hsl(var(--faint))", fontSize: 10 }}
            axisLine={{ stroke: "hsl(var(--line))" }}
            tickLine={false}
            minTickGap={24}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: "hsl(var(--faint))", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={38}
          />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--surface))",
              border: "1px solid hsl(var(--line))",
              borderRadius: 8,
              fontSize: 12,
              color: "hsl(var(--ink))",
            }}
            labelFormatter={(value: string) => date(value)}
            formatter={(value: number) => [value, "Signals"]}
          />
          <Area
            type="monotone"
            dataKey="signals"
            stroke="hsl(var(--accent))"
            strokeWidth={1.75}
            fill="url(#breadth)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
