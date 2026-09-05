import type { Metadata } from "next";

import { DataPage } from "@/features/data/DataPage";

export const metadata: Metadata = { title: "Data manager" };

export default function Page() {
  return <DataPage />;
}
