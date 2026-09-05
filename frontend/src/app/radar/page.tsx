import type { Metadata } from "next";

import { RadarPage } from "@/features/radar/RadarPage";

export const metadata: Metadata = { title: "Early warning radar" };

export default function Page() {
  return <RadarPage />;
}
