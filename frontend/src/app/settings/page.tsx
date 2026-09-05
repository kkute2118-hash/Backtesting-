import type { Metadata } from "next";

import { SettingsPage } from "@/features/settings/SettingsPage";

export const metadata: Metadata = { title: "Settings" };

export default function Page() {
  return <SettingsPage />;
}
