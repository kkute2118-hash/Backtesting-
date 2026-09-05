"use client";

import { CheckCircle2, CircleX, Loader2, XCircle } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Progress } from "@/components/ui/States";
import { useCancelJob } from "@/hooks/queries";
import { duration } from "@/lib/format";
import type { Job } from "@/types/api";

/**
 * Live state of a running scan.
 *
 * Shown instead of a blocking spinner: the rest of the page stays usable, the
 * message says what the engine is actually doing ("Evaluating 486 stocks
 * against 4 strategies") and the run can be cancelled, which the old
 * all-or-nothing spinner could not offer.
 */
export function JobProgress({ job, onDismiss }: { job: Job; onDismiss?: () => void }) {
  const cancel = useCancelJob();
  const isRunning = job.status === "queued" || job.status === "running";

  const elapsed =
    job.started_at && job.finished_at
      ? (new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1000
      : null;

  if (job.status === "failed") {
    return (
      <Card className="border-down/40 bg-down-soft/30">
        <div className="flex items-start gap-3 p-3.5">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-down" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-ink">{job.label} failed</p>
            <p className="mt-0.5 text-xs leading-relaxed text-muted">
              {job.error ?? "The run stopped without a reason."}
            </p>
          </div>
          {onDismiss ? (
            <Button size="sm" variant="ghost" onClick={onDismiss}>Dismiss</Button>
          ) : null}
        </div>
      </Card>
    );
  }

  if (job.status === "cancelled") {
    return (
      <Card className="border-warn/40 bg-warn-soft/30">
        <div className="flex items-center gap-3 p-3.5">
          <CircleX className="h-4 w-4 shrink-0 text-warn" aria-hidden />
          <p className="flex-1 text-xs text-ink">{job.label} was cancelled.</p>
          {onDismiss ? (
            <Button size="sm" variant="ghost" onClick={onDismiss}>Dismiss</Button>
          ) : null}
        </div>
      </Card>
    );
  }

  if (job.status === "succeeded") {
    return (
      <Card className="border-up/30 bg-up-soft/30">
        <div className="flex items-center gap-3 p-3.5">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-up" aria-hidden />
          <p className="flex-1 text-xs text-ink">
            {job.label} complete
            {elapsed !== null ? (
              <span className="text-muted"> in {duration(elapsed)}</span>
            ) : null}
            .
          </p>
          {onDismiss ? (
            <Button size="sm" variant="ghost" onClick={onDismiss}>Dismiss</Button>
          ) : null}
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="space-y-2.5 p-3.5">
        <div className="flex items-center gap-3">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-accent" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-ink">{job.label}</p>
            <p className="truncate text-2xs text-muted">{job.message}</p>
          </div>
          {isRunning ? (
            <Button
              size="sm"
              variant="ghost"
              loading={cancel.isPending}
              onClick={() => cancel.mutate(job.id)}
            >
              Cancel
            </Button>
          ) : null}
        </div>
        <Progress value={job.progress} />
      </div>
    </Card>
  );
}
