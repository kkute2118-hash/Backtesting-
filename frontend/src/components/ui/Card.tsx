import { cn } from "@/lib/utils";
import type { HTMLAttributes, ReactNode } from "react";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      // min-w-0: a grid/flex item's automatic minimum size is its content
      // width, so without this a wide table inside a card widens the whole
      // page instead of scrolling within the card.
      className={cn("min-w-0 rounded-card border border-line bg-surface shadow-card",
        className)}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  description,
  action,
  className,
  icon,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  icon?: ReactNode;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 border-b border-line px-4 py-3",
      className)}>
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-sm font-semibold tracking-tight text-ink">
          {icon}
          {title}
        </h2>
        {description ? (
          <p className="mt-0.5 text-xs leading-relaxed text-muted">{description}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...props} />;
}
