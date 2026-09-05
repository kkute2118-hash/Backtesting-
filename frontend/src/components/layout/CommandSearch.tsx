"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useDebounced, useDismiss } from "@/components/ui/Inputs";
import { useStockSearch } from "@/hooks/queries";
import { cn } from "@/lib/utils";

/**
 * Symbol search in the header, reachable with "/" from anywhere.
 *
 * It searches the local candle store rather than an instrument list, because a
 * stock we hold no candles for would open onto an empty detail page. The result
 * count of stored bars is shown for the same reason.
 */
export function CommandSearch() {
  const router = useRouter();
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useDismiss(() => setOpen(false));

  const debounced = useDebounced(term, 200);
  const { data, isFetching } = useStockSearch(debounced);
  const results = data?.results ?? [];

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typingElsewhere =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (event.key === "/" && !typingElsewhere) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => setHighlight(0), [debounced]);

  function go(symbol: string) {
    setOpen(false);
    setTerm("");
    inputRef.current?.blur();
    router.push(`/stocks/${encodeURIComponent(symbol)}`);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlight((index) => Math.min(index + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const chosen = results[highlight]?.symbol ?? term.trim().toUpperCase();
      if (chosen) go(chosen);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className="relative w-full max-w-xs">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5
        -translate-y-1/2 text-faint" aria-hidden />
      <input
        ref={inputRef}
        type="search"
        value={term}
        role="combobox"
        aria-expanded={open}
        aria-controls="symbol-results"
        aria-autocomplete="list"
        placeholder="Search symbol…"
        onChange={(event) => {
          setTerm(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        className="w-full rounded-md border border-line bg-elevated py-1.5 pl-8 pr-10 text-sm
          text-ink placeholder:text-faint hover:border-strongline focus:border-accent
          focus:outline-none"
      />
      <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded
        border border-line px-1 text-2xs text-faint">/</kbd>

      {open && debounced.trim() ? (
        <div
          id="symbol-results"
          role="listbox"
          className="absolute left-0 right-0 top-10 z-40 overflow-hidden rounded-md border
            border-line bg-surface shadow-pop animate-fade-in"
        >
          {isFetching && results.length === 0 ? (
            <p className="px-3 py-2.5 text-xs text-muted">Searching…</p>
          ) : results.length === 0 ? (
            <p className="px-3 py-2.5 text-xs text-muted">
              No stored stock matches “{debounced}”. Sync it from Data Manager first.
            </p>
          ) : (
            <ul className="max-h-72 overflow-y-auto scroll-thin py-1">
              {results.map((result, index) => (
                <li key={result.symbol}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={index === highlight}
                    onMouseEnter={() => setHighlight(index)}
                    onClick={() => go(result.symbol)}
                    className={cn(
                      "flex w-full items-baseline justify-between gap-3 px-3 py-1.5 text-left",
                      index === highlight ? "bg-elevated" : "hover:bg-elevated/60",
                    )}
                  >
                    <span className="text-xs font-semibold text-ink">{result.symbol}</span>
                    <span className="tabular text-2xs text-faint">
                      {result.bars.toLocaleString("en-IN")} bars
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
