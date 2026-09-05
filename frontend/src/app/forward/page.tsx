import type { Metadata } from "next";

import { ForwardPage } from "@/features/forward/ForwardPage";

export const metadata: Metadata = { title: "Forward tests" };

export default function Page() {
  return <ForwardPage />;
}
