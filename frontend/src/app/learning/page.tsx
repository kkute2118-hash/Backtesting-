import type { Metadata } from "next";

import { LearningPage } from "@/features/learning/LearningPage";

export const metadata: Metadata = { title: "Learning" };

export default function Page() {
  return <LearningPage />;
}
