import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Every page opens the same way: title, one line of context, then actions. */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3", className)}>
      <div className="min-w-0">
        <h1 className="text-lg font-semibold tracking-tight text-ink sm:text-xl">{title}</h1>
        {description ? (
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("mx-auto w-full max-w-[1600px] space-y-5 px-3 py-5 sm:px-5 sm:py-6",
      className)}>
      {children}
    </div>
  );
}
