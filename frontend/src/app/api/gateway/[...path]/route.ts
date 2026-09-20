/**
 * Server-side proxy for state-changing requests.
 *
 * The backend requires X-API-Key on every POST/PUT/PATCH/DELETE. That key
 * cannot live in the browser bundle - anything reachable from client code is
 * readable by anyone who opens devtools, and NEXT_PUBLIC_* is compiled in
 * literally. So mutations go to this route handler, which runs on the Next
 * server, reads API_ACCESS_KEY from its own environment and forwards.
 *
 * Reads are not proxied: they are open on the backend and going through here
 * would add a hop to every page load for no benefit.
 */
import { NextRequest, NextResponse } from "next/server";

const ALLOWED = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * Where the backend is, resolved PER REQUEST.
 *
 * Not a module-scope constant, and API_BACKEND_URL before the public one:
 * NEXT_PUBLIC_* values are inlined into the bundle at BUILD time, so a
 * server-side read of one returns whatever was set when the image was built
 * and silently ignores the running environment. That cost a 502 on every
 * mutation locally, and would have done the same in production had the build
 * not happened to carry the right value.
 */
function backendBase(): string {
  const raw = process.env.API_BACKEND_URL
    || process.env.NEXT_PUBLIC_API_URL
    || "http://localhost:8000";
  return raw.replace(/\/$/, "");
}

async function forward(request: NextRequest, path: string[]) {
  if (!ALLOWED.has(request.method)) {
    return NextResponse.json(
      { code: "method_not_allowed", message: "This proxy forwards mutations only." },
      { status: 405 },
    );
  }
  // Join from the matched segments, never from raw user input, so a crafted
  // path cannot address something outside the backend's API.
  const target =
    `${backendBase()}/api/v1/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const key = process.env.API_ACCESS_KEY;
  if (key) headers["X-API-Key"] = key;

  let body: string | undefined;
  try {
    body = await request.text();
  } catch {
    body = undefined;
  }

  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: body || undefined,
      cache: "no-store",
    });
    const text = await response.text();
    return new NextResponse(text, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch (cause) {
    // Never echo the upstream URL or the key to the client - but do log the
    // reason server-side, because "cannot reach" with no detail is what made
    // the build-time inlining above take so long to spot.
    console.error("gateway: upstream request failed", cause);
    return NextResponse.json(
      { code: "network_error", message: "Cannot reach the analysis server." },
      { status: 502 },
    );
  }
}

export async function POST(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path);
}
export async function PUT(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path);
}
export async function PATCH(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path);
}
export async function DELETE(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path);
}
