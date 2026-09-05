import type { Metadata } from "next";

import { BacktestPage } from "@/features/backtest/BacktestPage";

export const metadata: Metadata = { title: "Backtest" };

export default function Page() {
  return <BacktestPage />;
}
