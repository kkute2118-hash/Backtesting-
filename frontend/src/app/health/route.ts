/**
 * Liveness for the Next server itself. Render's health check calls this.
 *
 * Deliberately says nothing about the API. A health check that failed when
 * the backend was asleep would have Render replace a perfectly healthy web
 * instance for a condition it cannot fix - and on the free plan the backend
 * is asleep most of the time. "Is this server answering?" is the only
 * question this route is allowed to answer.
 *
 * force-dynamic and no-store because a cached 200 is not a health check: it
 * would keep reporting success from a process that had stopped working.
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export function GET() {
  return NextResponse.json(
    { status: "ok", service: "ati-lab-web" },
    { headers: { "Cache-Control": "no-store, max-age=0" } },
  );
}
