import type { Metadata } from "next";

import { SectorsPage } from "@/features/sectors/SectorsPage";

export const metadata: Metadata = { title: "Sector strength" };

export default function Page() {
  return <SectorsPage />;
}
