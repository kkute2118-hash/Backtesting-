"use client";

import { Check, ChevronDown, Search, X } from "lucide-react";
import {
  forwardRef, useEffect, useId, useRef, useState,
  type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes,
} from "react";

import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-md border border-line bg-elevated px-2.5 py-1.5 text-sm text-ink " +
  "placeholder:text-faint transition-colors hover:border-strongline " +
  "focus:border-accent focus:outline-none disabled:opacity-50";

export function Field({
  label,
  hint,
  children,
  htmlFor,
  className,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={htmlFor} className="block text-xs font-medium text-muted">
        {label}
      </label>
      {children}
      {hint ? <p className="text-2xs leading-relaxed text-faint">{hint}</p> : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(FIELD, className)} {...props} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...props }, ref) {
    return (
      <div className="relative">
        <select ref={ref} className={cn(FIELD, "appearance-none pr-8", className)} {...props}>
          {children}
        </select>
        <ChevronDown
          className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint"
          aria-hidden
        />
      </div>
    );
  },
);

export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5
        -translate-y-1/2 text-faint" aria-hidden />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className={cn(FIELD, "pl-8", value && "pr-8")}
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Clear search"
          className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-ink"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start gap-3">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "mt-0.5 h-4.5 w-8 shrink-0 rounded-full border transition-colors duration-150",
          "disabled:opacity-50",
          checked ? "border-accent bg-accent" : "border-strongline bg-elevated",
        )}
        style={{ height: "1.125rem" }}
      >
        <span
          className={cn(
            "block h-3 w-3 rounded-full bg-white transition-transform duration-150",
            checked ? "translate-x-[1.125rem]" : "translate-x-0.5",
          )}
        />
      </button>
      <label htmlFor={id} className="cursor-pointer select-none">
        <span className="block text-xs font-medium text-ink">{label}</span>
        {description ? (
          <span className="mt-0.5 block text-2xs leading-relaxed text-faint">{description}</span>
        ) : null}
      </label>
    </div>
  );
}

export function CheckboxGroup<T extends string | number>({
  options,
  selected,
  onChange,
  columns = 2,
}: {
  options: Array<{ value: T; label: string; hint?: string; disabled?: boolean }>;
  selected: T[];
  onChange: (values: T[]) => void;
  columns?: number;
}) {
  function toggle(value: T) {
    onChange(selected.includes(value)
      ? selected.filter((entry) => entry !== value)
      : [...selected, value]);
  }
  return (
    <div className={cn("grid gap-1.5", columns === 1 ? "grid-cols-1" : "grid-cols-2")}>
      {options.map((option) => {
        const isSelected = selected.includes(option.value);
        return (
          <button
            key={String(option.value)}
            type="button"
            role="checkbox"
            aria-checked={isSelected}
            disabled={option.disabled}
            onClick={() => toggle(option.value)}
            title={option.hint}
            className={cn(
              "flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-xs",
              "transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-40",
              isSelected
                ? "border-accent/40 bg-accent-soft text-ink"
                : "border-line bg-elevated text-muted hover:border-strongline hover:text-ink",
            )}
          >
            <span
              className={cn(
                "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border",
                isSelected ? "border-accent bg-accent" : "border-strongline",
              )}
              aria-hidden
            >
              {isSelected ? <Check className="h-2.5 w-2.5 text-white" /> : null}
            </span>
            <span className="min-w-0 truncate">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** A range slider paired with the exact number, because both matter here. */
export function RangeField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix,
  hint,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="text-xs font-medium text-muted">{label}</label>
        <span className="tabular text-xs font-semibold text-ink">
          {value}
          {suffix}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-1 w-full cursor-pointer appearance-none rounded-full bg-elevated
          accent-[hsl(var(--accent))]"
      />
      {hint ? <p className="text-2xs text-faint">{hint}</p> : null}
    </div>
  );
}

/** Optional numeric bound. Empty means "no bound", which is not the same as 0. */
export function BoundInput({
  label,
  value,
  onChange,
  placeholder,
  step = "any",
}: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  placeholder?: string;
  step?: string;
}) {
  const id = useId();
  return (
    <Field label={label} htmlFor={id}>
      <Input
        id={id}
        type="number"
        step={step}
        value={value ?? ""}
        placeholder={placeholder ?? "Any"}
        onChange={(event) =>
          onChange(event.target.value === "" ? null : Number(event.target.value))
        }
      />
    </Field>
  );
}

/** Debounce a fast-changing value so typing does not fire a request per keystroke. */
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** Close a popover on an outside click or Escape — both, always. */
export function useDismiss(onDismiss: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) onDismiss();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onDismiss();
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onDismiss]);
  return ref;
}
