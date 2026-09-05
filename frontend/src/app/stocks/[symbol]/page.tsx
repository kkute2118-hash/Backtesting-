import type { Metadata } from "next";

import { StockPage } from "@/features/stocks/StockPage";

export async function generateMetadata(
  { params }: { params: Promise<{ symbol: string }> },
): Promise<Metadata> {
  const { symbol } = await params;
  return { title: decodeURIComponent(symbol).toUpperCase() };
}

export default async function Page({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  return <StockPage symbol={decodeURIComponent(symbol).toUpperCase()} />;
}
