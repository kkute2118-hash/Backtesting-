"use client";

import { Eye, FolderPlus, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge, toneForSafety } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Field, Input } from "@/components/ui/Inputs";
import { Change, Note, ScoreBar, SymbolLink } from "@/components/ui/Misc";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import {
  useAddToWatchlist, useCreateWatchlist, useDeleteWatchlist, useRemoveFromWatchlist,
  useWatchlists,
} from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { compact, date, inr } from "@/lib/format";
import type { Watchlist } from "@/types/api";

export function WatchlistPage() {
  const { data: watchlists, isLoading, error, refetch } = useWatchlists(true);
  const createWatchlist = useCreateWatchlist();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  async function create() {
    if (!name.trim()) return;
    try {
      await createWatchlist.mutateAsync({ name: name.trim() });
      toast.success(`Created “${name.trim()}”`);
      setName("");
      setCreating(false);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  return (
    <Page>
      <PageHeader
        title="Watchlists"
        description="Groups of stocks you are tracking, with the last stored price, today's move
          and the scanner's most recent verdict on each."
        actions={
          <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
            <FolderPlus className="h-3.5 w-3.5" aria-hidden />
            New watchlist
          </Button>
        }
      />

      {creating ? (
        <Card>
          <CardBody className="flex flex-wrap items-end gap-2">
            <Field label="Name" className="min-w-[16rem] flex-1" htmlFor="watchlist-name">
              <Input
                id="watchlist-name"
                autoFocus
                value={name}
                placeholder="e.g. Breakout candidates"
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") create();
                  if (event.key === "Escape") setCreating(false);
                }}
              />
            </Field>
            <Button variant="primary" loading={createWatchlist.isPending}
              disabled={!name.trim()} onClick={create}>
              Create
            </Button>
            <Button variant="ghost" onClick={() => { setCreating(false); setName(""); }}>
              Cancel
            </Button>
          </CardBody>
        </Card>
      ) : null}

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-48 w-full rounded-card" />
          <Skeleton className="h-48 w-full rounded-card" />
        </div>
      ) : error ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : (watchlists ?? []).length === 0 ? (
        <Card>
          <EmptyState
            icon={<Eye className="h-6 w-6" />}
            title="No watchlists yet"
            message="Create one and add stocks from a scan result or a stock's own page. Prices
              and the latest scanner verdict are attached automatically."
            action={
              <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
                <FolderPlus className="h-3.5 w-3.5" aria-hidden />
                Create a watchlist
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="space-y-5">
          {(watchlists ?? []).map((list) => (
            <WatchlistCard key={list.id} list={list} />
          ))}
        </div>
      )}

      <Note>
        Watchlists are stored in the same database as your candles and forward tests, so they are
        covered by the GitHub backup and survive a container restart.
      </Note>
    </Page>
  );
}

function WatchlistCard({ list }: { list: Watchlist }) {
  const addSymbols = useAddToWatchlist();
  const removeSymbol = useRemoveFromWatchlist();
  const deleteWatchlist = useDeleteWatchlist();
  const [symbol, setSymbol] = useState("");
  const [confirming, setConfirming] = useState(false);

  async function add() {
    const clean = symbol.trim().toUpperCase();
    if (!clean) return;
    try {
      await addSymbols.mutateAsync({ id: list.id, symbols: [clean] });
      setSymbol("");
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <Card>
      <CardHeader
        title={list.name}
        description={
          `${list.count} stock${list.count === 1 ? "" : "s"}` +
          (list.description ? ` · ${list.description}` : "")
        }
        action={
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1">
              <Input
                value={symbol}
                placeholder="Add symbol"
                aria-label={`Add a symbol to ${list.name}`}
                onChange={(event) => setSymbol(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") add(); }}
                className="h-8 w-32"
              />
              <Button size="icon" variant="secondary" onClick={add}
                loading={addSymbols.isPending} aria-label="Add symbol">
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </div>
            {confirming ? (
              <div className="flex items-center gap-1">
                <Button size="sm" variant="danger" loading={deleteWatchlist.isPending}
                  onClick={() => deleteWatchlist.mutate(list.id)}>
                  Delete list
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <Button size="icon" variant="ghost" onClick={() => setConfirming(true)}
                aria-label={`Delete ${list.name}`}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        }
      />

      {list.items.length === 0 ? (
        <EmptyState
          title="Empty"
          message="Add a symbol above, or use the button on any stock's page."
        />
      ) : (
        <div className="overflow-x-auto scroll-thin">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
                <th scope="col" className="px-4 py-2 text-left font-semibold">Symbol</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">Price</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">Change</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">Volume</th>
                <th scope="col" className="px-4 py-2 text-left font-semibold">Last signal</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">Score</th>
                <th scope="col" className="px-4 py-2 text-left font-semibold">Safety</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((item) => (
                <tr key={item.id} className="border-b border-line/60 last:border-0
                  hover:bg-elevated/50">
                  <td className="px-4 py-2"><SymbolLink symbol={item.symbol} /></td>
                  <td className="tabular px-4 py-2 text-right">
                    {item.price === null || item.price === undefined ? (
                      <span className="text-faint" title="No stored candles for this symbol">
                        no data
                      </span>
                    ) : (
                      inr(item.price)
                    )}
                  </td>
                  <td className="px-4 py-2 text-right"><Change value={item.change_pct} /></td>
                  <td className="tabular px-4 py-2 text-right text-muted">
                    {compact(item.volume)}
                  </td>
                  <td className="px-4 py-2">
                    {item.signal_strategy ? (
                      <span className="flex items-center gap-1.5">
                        <Badge tone="accent">{item.signal_strategy}</Badge>
                        <span className="text-2xs text-faint">{date(item.signal_date)}</span>
                      </span>
                    ) : (
                      <span className="text-2xs text-faint">Never qualified</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <ScoreBar score={item.signal_score ?? null} />
                  </td>
                  <td className="px-4 py-2">
                    {item.signal_safety ? (
                      <Badge tone={toneForSafety(item.signal_safety)}>{item.signal_safety}</Badge>
                    ) : (
                      <span className="text-faint">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      type="button"
                      onClick={() =>
                        removeSymbol.mutate({ id: list.id, symbol: item.symbol })}
                      aria-label={`Remove ${item.symbol} from ${list.name}`}
                      className="rounded p-1 text-faint hover:text-down"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
