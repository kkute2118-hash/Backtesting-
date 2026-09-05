import type { Metadata } from "next";

import { ResearchPage } from "@/features/research/ResearchPage";

export const metadata: Metadata = { title: "Research lab" };

export default function Page() {
  return <ResearchPage />;
}
