import type { Metadata } from "next";

import { ResultsPage } from "@/features/scanner/ResultsPage";

export const metadata: Metadata = { title: "Scan results" };

export default async function Page({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <ResultsPage runId={runId} />;
}
