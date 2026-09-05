import type { Metadata } from "next";

import { ScannerPage } from "@/features/scanner/ScannerPage";

export const metadata: Metadata = { title: "Scanner" };

export default function Page() {
  return <ScannerPage />;
}
