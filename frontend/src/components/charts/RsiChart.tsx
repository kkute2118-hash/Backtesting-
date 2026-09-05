"use client";

import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { date, num } from "@/lib/format";

/**
 * Daily RSI beneath the price chart.
 *
 * 30/70 are drawn as reference lines because that is the conventional reading,
 * but 50 gets the emphasis: several of this engine's rules gate on RSI ≥ 50,
 * so that is the level that decides whether a stock qualifies.
 */
export function RsiChart({
  data,
}: {
  data: Array<{ time: string; value: number | null }>;
}) {
  const points = data.filter((point) => point.value !== null);
  if (points.length === 0) return null;

  return (
    <div className="h-32 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
          <CartesianGrid stroke="hsl(var(--line))" strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="time" hide />
          <YAxis
            domain={[0, 100]}
            ticks={[30, 50, 70]}
            tick={{ fill: "hsl(var(--faint))", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={34}
          />
          <ReferenceLine y={70} stroke="hsl(var(--line))" strokeDasharray="3 3" />
          <ReferenceLine y={50} stroke="hsl(var(--accent))" strokeOpacity={0.5} />
          <ReferenceLine y={30} stroke="hsl(var(--line))" strokeDasharray="3 3" />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--surface))",
              border: "1px solid hsl(var(--line))",
              borderRadius: 8,
              fontSize: 12,
              color: "hsl(var(--ink))",
            }}
            labelFormatter={(value: string) => date(value)}
            formatter={(value: number) => [num(value, 1), "RSI(14)"]}
          />
          <Line type="monotone" dataKey="value" stroke="hsl(var(--accent))" strokeWidth={1.5}
            dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
