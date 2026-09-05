import type { Metadata } from "next";

import { WatchlistPage } from "@/features/watchlist/WatchlistPage";

export const metadata: Metadata = { title: "Watchlists" };

export default function Page() {
  return <WatchlistPage />;
}
