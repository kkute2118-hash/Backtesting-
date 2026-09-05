"use client";

import { Bookmark, BookmarkPlus, Lock, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Inputs";
import { Skeleton } from "@/components/ui/States";
import { useCreatePreset, useDeletePreset, usePresets } from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Preset } from "@/types/api";

import type { ScanFormState } from "./shared";

/**
 * Saved scanner configurations.
 *
 * Only options the engine really accepts can be saved — universes, which of
 * S1-S4 to evaluate, the score gate, the live overlay. There is no
 * "Oversold" or "Volume Surge" preset because the engine implements no such
 * screen, and shipping one would mean inventing a rule the scanner never runs.
 */
export function PresetBar({
  current,
  onApply,
}: {
  current: ScanFormState;
  onApply: (preset: Preset) => void;
}) {
  const { data: presets, isLoading } = usePresets();
  const createPreset = useCreatePreset();
  const deletePreset = useDeletePreset();
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");

  async function save() {
    if (!name.trim()) return;
    try {
      await createPreset.mutateAsync({
        name: name.trim(),
        config: {
          universes: current.universes,
          strategies: current.strategies,
          min_score: current.min_score,
          use_live_prices: current.use_live_prices,
          limit: current.limit,
        },
      });
      toast.success(`Saved “${name.trim()}”`);
      setName("");
      setSaving(false);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  async function remove(preset: Preset) {
    try {
      await deletePreset.mutateAsync(preset.id);
      toast.success(`Deleted “${preset.name}”`);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  if (isLoading) {
    return (
      <div className="flex gap-2">
        {[0, 1, 2].map((index) => <Skeleton key={index} className="h-7 w-40" />)}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {(presets ?? []).map((preset) => {
          const isCurrent =
            preset.config.min_score === current.min_score &&
            preset.config.use_live_prices === current.use_live_prices &&
            preset.config.universes.join() === current.universes.join() &&
            preset.config.strategies.join() === current.strategies.join();
          return (
            <div key={preset.id} className="group relative">
              <button
                type="button"
                onClick={() => onApply(preset)}
                title={preset.description ?? undefined}
                className={cn(
                  "flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs",
                  "transition-colors duration-150",
                  isCurrent
                    ? "border-accent/40 bg-accent-soft text-ink"
                    : "border-line bg-elevated text-muted hover:border-strongline hover:text-ink",
                  !preset.builtin && "pr-7",
                )}
              >
                {preset.builtin ? (
                  <Lock className="h-3 w-3 text-faint" aria-hidden />
                ) : (
                  <Bookmark className="h-3 w-3 text-accent" aria-hidden />
                )}
                <span className="max-w-[16rem] truncate">{preset.name}</span>
              </button>
              {!preset.builtin ? (
                <button
                  type="button"
                  onClick={() => remove(preset)}
                  aria-label={`Delete preset ${preset.name}`}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-faint
                    opacity-0 transition-opacity hover:text-down group-hover:opacity-100
                    focus-visible:opacity-100"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              ) : null}
            </div>
          );
        })}

        {saving ? null : (
          <Button size="sm" variant="ghost" onClick={() => setSaving(true)}>
            <BookmarkPlus className="h-3.5 w-3.5" aria-hidden />
            Save current
          </Button>
        )}
      </div>

      {saving ? (
        <div className="flex items-end gap-2 rounded-md border border-line bg-elevated p-2.5">
          <Field label="Preset name" className="flex-1" htmlFor="preset-name">
            <Input
              id="preset-name"
              autoFocus
              value={name}
              placeholder="e.g. Smallcap momentum ≥80"
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") save();
                if (event.key === "Escape") setSaving(false);
              }}
            />
          </Field>
          <Button size="md" variant="primary" loading={createPreset.isPending}
            onClick={save} disabled={!name.trim()}>
            Save
          </Button>
          <Button size="md" variant="ghost" onClick={() => { setSaving(false); setName(""); }}>
            Cancel
          </Button>
        </div>
      ) : null}

      <p className="text-2xs leading-relaxed text-faint">
        <Badge tone="neutral" className="mr-1.5">Built in</Badge>
        presets are read-only reference configurations. Save your own to keep a
        setup you return to.
      </p>
    </div>
  );
}
