"use client";

import { ArrowDown, ArrowUp, ChevronsUpDown, Columns3, Download } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";
import type { Row } from "@/types/api";

import { Button } from "./Button";
import { useDismiss } from "./Inputs";
import { EmptyState } from "./States";

export interface Column<T> {
  /** Stable key; also the export header. */
  key: string;
  header: string;
  /** Cell content. Return a string for the default right-aligned numeric look. */
  render: (row: T) => ReactNode;
  /** Raw value used for sorting and CSV export. */
  value?: (row: T) => string | number | null;
  align?: "left" | "right";
  width?: string;
  /** Frozen columns stay visible while the rest scrolls horizontally. */
  sticky?: boolean;
  sortable?: boolean;
  /** Hidden until the user turns it on in the column menu. */
  optional?: boolean;
  description?: string;
}

export interface DataTableProps<T> {
  rows: T[];
  columns: Column<T>[];
  getRowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  selectable?: boolean;
  selected?: string[];
  onSelectionChange?: (ids: string[]) => void;
  sort?: { key: string; dir: "asc" | "desc" };
  onSortChange?: (sort: { key: string; dir: "asc" | "desc" }) => void;
  emptyTitle?: string;
  emptyMessage?: ReactNode;
  emptyAction?: ReactNode;
  exportName?: string;
  toolbar?: ReactNode;
  /** Rows kept in the DOM. Beyond this the table paginates instead. */
  maxHeight?: string;
}

/**
 * The results table.
 *
 * Everything a screening tool needs and `st.dataframe` could not do: sortable
 * headers, a frozen symbol column so a row stays identifiable while the
 * numbers scroll, per-column visibility, row selection that feeds the
 * forward-test action, and a CSV export of exactly what is on screen.
 *
 * Sorting is delegated upward when `onSortChange` is given, because the scanner
 * sorts server-side over the whole result set rather than only the page in view.
 */
export function DataTable<T extends Row>({
  rows,
  columns,
  getRowId,
  onRowClick,
  selectable,
  selected = [],
  onSelectionChange,
  sort,
  onSortChange,
  emptyTitle = "Nothing to show",
  emptyMessage,
  emptyAction,
  exportName,
  toolbar,
  maxHeight = "calc(100vh - 22rem)",
}: DataTableProps<T>) {
  const [hidden, setHidden] = useState<string[]>(
    () => columns.filter((column) => column.optional).map((column) => column.key),
  );
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useDismiss(() => setMenuOpen(false));

  const visible = useMemo(
    () => columns.filter((column) => !hidden.includes(column.key)),
    [columns, hidden],
  );

  const allSelected = rows.length > 0 && rows.every((row) => selected.includes(getRowId(row)));

  function toggleAll() {
    if (!onSelectionChange) return;
    onSelectionChange(allSelected ? [] : rows.map(getRowId));
  }

  function toggleRow(id: string) {
    if (!onSelectionChange) return;
    onSelectionChange(
      selected.includes(id) ? selected.filter((entry) => entry !== id) : [...selected, id],
    );
  }

  function requestSort(column: Column<T>) {
    if (!onSortChange || column.sortable === false) return;
    const dir = sort?.key === column.key && sort.dir === "desc" ? "asc" : "desc";
    onSortChange({ key: column.key, dir });
  }

  function exportCsv() {
    const header = visible.map((column) => `"${column.header}"`).join(",");
    const body = rows
      .map((row) =>
        visible
          .map((column) => {
            const raw = column.value ? column.value(row) : (row[column.key] ?? "");
            const text = raw === null || raw === undefined ? "" : String(raw);
            return `"${text.replace(/"/g, '""')}"`;
          })
          .join(","),
      )
      .join("\n");
    const blob = new Blob([`${header}\n${body}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${exportName ?? "results"}-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex min-h-0 flex-col">
      {(toolbar || exportName) && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{toolbar}</div>
          <div className="relative flex items-center gap-1" ref={menuRef}>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-haspopup="true"
            >
              <Columns3 className="h-3.5 w-3.5" aria-hidden />
              Columns
            </Button>
            {exportName ? (
              <Button size="sm" variant="ghost" onClick={exportCsv} disabled={rows.length === 0}>
                <Download className="h-3.5 w-3.5" aria-hidden />
                Export
              </Button>
            ) : null}
            {menuOpen ? (
              <div className="absolute right-0 top-9 z-30 w-60 rounded-md border border-line
                bg-surface p-1.5 shadow-pop animate-fade-in">
                <p className="px-2 py-1 text-2xs font-semibold uppercase tracking-wide text-faint">
                  Visible columns
                </p>
                <div className="max-h-72 overflow-y-auto scroll-thin">
                  {columns.map((column) => {
                    const isVisible = !hidden.includes(column.key);
                    return (
                      <label
                        key={column.key}
                        className="flex cursor-pointer items-center gap-2 rounded px-2 py-1
                          text-xs text-muted hover:bg-elevated hover:text-ink"
                      >
                        <input
                          type="checkbox"
                          checked={isVisible}
                          onChange={() =>
                            setHidden((current) =>
                              isVisible
                                ? [...current, column.key]
                                : current.filter((key) => key !== column.key),
                            )
                          }
                          className="h-3 w-3 accent-[hsl(var(--accent))]"
                        />
                        <span className="truncate">{column.header}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState title={emptyTitle} message={emptyMessage} action={emptyAction} />
      ) : (
        <div className="min-h-0 overflow-auto scroll-thin" style={{ maxHeight }}>
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 z-20 bg-surface">
              <tr className="border-b border-strongline">
                {selectable ? (
                  <th scope="col" className="sticky left-0 z-20 w-9 bg-surface px-3 py-2">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      aria-label="Select all rows"
                      className="h-3 w-3 accent-[hsl(var(--accent))]"
                    />
                  </th>
                ) : null}
                {visible.map((column) => {
                  const isSorted = sort?.key === column.key;
                  const canSort = onSortChange && column.sortable !== false;
                  return (
                    <th
                      key={column.key}
                      scope="col"
                      title={column.description}
                      aria-sort={
                        isSorted ? (sort!.dir === "asc" ? "ascending" : "descending") : "none"
                      }
                      style={{ width: column.width }}
                      className={cn(
                        "whitespace-nowrap px-3 py-2 font-semibold uppercase tracking-wide",
                        "text-2xs text-faint",
                        column.align === "right" ? "text-right" : "text-left",
                        column.sticky && "sticky left-0 z-20 bg-surface",
                        column.sticky && selectable && "left-9",
                      )}
                    >
                      {canSort ? (
                        <button
                          type="button"
                          onClick={() => requestSort(column)}
                          className={cn(
                            "inline-flex items-center gap-1 hover:text-ink",
                            column.align === "right" && "flex-row-reverse",
                            isSorted && "text-accent",
                          )}
                        >
                          {column.header}
                          {isSorted ? (
                            sort!.dir === "asc" ? (
                              <ArrowUp className="h-3 w-3" aria-hidden />
                            ) : (
                              <ArrowDown className="h-3 w-3" aria-hidden />
                            )
                          ) : (
                            <ChevronsUpDown className="h-3 w-3 opacity-40" aria-hidden />
                          )}
                        </button>
                      ) : (
                        column.header
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const id = getRowId(row);
                const isSelected = selected.includes(id);
                return (
                  <tr
                    key={id}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    tabIndex={onRowClick ? 0 : undefined}
                    onKeyDown={
                      onRowClick
                        ? (event) => {
                            if (event.key === "Enter") onRowClick(row);
                          }
                        : undefined
                    }
                    className={cn(
                      "border-b border-line/60 transition-colors",
                      onRowClick && "cursor-pointer",
                      isSelected ? "bg-accent-soft/40" : "hover:bg-elevated/60",
                    )}
                  >
                    {selectable ? (
                      <td
                        className={cn(
                          "sticky left-0 z-10 px-3 py-1.5",
                          isSelected ? "bg-accent-soft/40" : "bg-surface",
                        )}
                        onClick={(event) => event.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleRow(id)}
                          aria-label={`Select ${id}`}
                          className="h-3 w-3 accent-[hsl(var(--accent))]"
                        />
                      </td>
                    ) : null}
                    {visible.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          "whitespace-nowrap px-3 py-1.5",
                          column.align === "right" ? "text-right tabular" : "text-left",
                          column.sticky && "sticky left-0 z-10 font-medium",
                          column.sticky && (isSelected ? "bg-accent-soft/40" : "bg-surface"),
                          column.sticky && selectable && "left-9",
                        )}
                      >
                        {column.render(row)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
