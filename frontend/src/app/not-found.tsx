import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 px-5 py-24 text-center">
      <p className="tabular text-3xl font-semibold text-faint">404</p>
      <h1 className="text-lg font-semibold text-ink">That page does not exist</h1>
      <p className="text-xs leading-relaxed text-muted">
        The link may be stale, or a scan run may have expired out of the history.
      </p>
      <Link
        href="/"
        className="mt-1 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white
          hover:bg-accent/90"
      >
        Back to the dashboard
      </Link>
    </div>
  );
}
