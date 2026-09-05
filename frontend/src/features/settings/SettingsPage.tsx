"use client";

import { CheckCircle2, Circle, Moon, Sun, Monitor } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { CheckboxGroup, Field, RangeField } from "@/components/ui/Inputs";
import { Note } from "@/components/ui/Misc";
import { Skeleton } from "@/components/ui/States";
import { STRATEGY_OPTIONS } from "@/features/scanner/shared";
import {
  useConfig, usePreferences, useSetPreference, useUniverses,
} from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { date } from "@/lib/format";
import { cn } from "@/lib/utils";

const PROVIDERS = [
  {
    key: "dhan" as const,
    name: "Dhan",
    purpose: "Instrument master, daily candles, bulk quotes and the live WebSocket feed. " +
      "Everything about Indian equities depends on it.",
    variables: "DHAN_CLIENT_ID, plus DHAN_PIN + DHAN_TOTP_SECRET (or DHAN_ACCESS_TOKEN)",
    required: true,
  },
  {
    key: "twelvedata" as const,
    name: "Twelve Data",
    purpose: "Fundamentals, news and event risk, and the forex/crypto SMC engine.",
    variables: "TWELVEDATA_API_KEY",
    required: false,
  },
  {
    key: "anthropic" as const,
    name: "Anthropic",
    purpose: "The optional AI coach, trade debate panel and system learning panel.",
    variables: "ANTHROPIC_API_KEY",
    required: false,
  },
  {
    key: "github_backup" as const,
    name: "GitHub backup",
    purpose: "Pushes the database so forward tests and accumulated learning survive a container " +
      "restart. Strongly recommended — this data cannot be rebuilt from anywhere.",
    variables: "GH_BACKUP_TOKEN, GH_REPO, DB_BACKUP_BRANCH",
    required: false,
  },
];

export function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const { data: config, isLoading } = useConfig();
  const { data: universes } = useUniverses();
  const { data: preferences } = usePreferences();
  const setPreference = useSetPreference();

  const [defaultUniverses, setDefaultUniverses] = useState<string[]>(["Nifty 500"]);
  const [defaultStrategies, setDefaultStrategies] = useState<number[]>([1, 2, 3, 4]);
  const [defaultGate, setDefaultGate] = useState(85);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!preferences) return;
    if (Array.isArray(preferences.default_universes)) {
      setDefaultUniverses(preferences.default_universes as string[]);
    }
    if (Array.isArray(preferences.default_strategies)) {
      setDefaultStrategies(preferences.default_strategies as number[]);
    }
    if (typeof preferences.default_gate === "number") {
      setDefaultGate(preferences.default_gate);
    }
  }, [preferences]);

  async function save() {
    try {
      await setPreference.mutateAsync({ key: "default_universes", value: defaultUniverses });
      await setPreference.mutateAsync({ key: "default_strategies", value: defaultStrategies });
      await setPreference.mutateAsync({ key: "default_gate", value: defaultGate });
      toast.success("Defaults saved");
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <Page>
      <PageHeader
        title="Settings"
        description="Configuration status and the defaults this application starts from.
          Credentials themselves live only in the backend environment — nothing here can read
          or set one."
      />

      <Card>
        <CardHeader title="Appearance" />
        <CardBody className="space-y-3">
          <Field label="Theme">
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Theme">
              {[
                { value: "dark", label: "Dark", icon: Moon,
                  hint: "The default. Long sessions, dense numbers." },
                { value: "light", label: "Light", icon: Sun, hint: "For bright rooms and print." },
                { value: "system", label: "System", icon: Monitor,
                  hint: "Follow the operating system." },
              ].map((option) => {
                const Icon = option.icon;
                const active = mounted && theme === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setTheme(option.value)}
                    title={option.hint}
                    className={cn(
                      "flex items-center gap-2 rounded-md border px-3 py-2 text-xs",
                      "transition-colors",
                      active
                        ? "border-accent/40 bg-accent-soft text-ink"
                        : "border-line bg-elevated text-muted hover:border-strongline",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                    {option.label}
                  </button>
                );
              })}
            </div>
          </Field>
          <Note>Your choice is stored in this browser and applies the moment you pick it.</Note>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Integrations"
          description="Whether each provider is configured. Values are never returned to the
            browser — only these booleans."
        />
        <CardBody className="space-y-2.5">
          {isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            PROVIDERS.map((provider) => {
              const status = config?.providers[provider.key];
              const configured = status?.configured ?? false;
              return (
                <div key={provider.key}
                  className="flex flex-wrap items-start gap-3 rounded-md border border-line
                    bg-elevated p-3">
                  <span className="mt-0.5 shrink-0" aria-hidden>
                    {configured
                      ? <CheckCircle2 className="h-4 w-4 text-up" />
                      : <Circle className={cn("h-4 w-4",
                          provider.required ? "text-down" : "text-faint")} />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-xs font-semibold text-ink">{provider.name}</p>
                      <Badge tone={configured ? "up" : provider.required ? "down" : "neutral"}>
                        {configured ? "Configured" : provider.required ? "Required" : "Optional"}
                      </Badge>
                      {provider.key === "dhan" && status && "auto_renew" in status
                        && status.auto_renew ? (
                        <Badge tone="accent">Auto-renewing token</Badge>
                      ) : null}
                    </div>
                    <p className="mt-1 text-2xs leading-relaxed text-muted">{provider.purpose}</p>
                    <p className="mt-1 font-mono text-2xs text-faint">{provider.variables}</p>
                    {provider.key === "dhan" && status && "token_issued_at" in status
                      && status.token_issued_at ? (
                      <p className="mt-1 text-2xs text-faint">
                        Current token minted {date(status.token_issued_at, true)}. Dhan expires
                        tokens every 24 hours.
                      </p>
                    ) : null}
                  </div>
                </div>
              );
            })
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Scan defaults"
          description="What the dashboard's freshness check and new scans start from."
        />
        <CardBody className="space-y-5">
          <Field label="Default universe">
            <CheckboxGroup
              options={(universes ?? []).map((universe) => ({
                value: universe.name, label: universe.name, disabled: !universe.available,
              }))}
              selected={defaultUniverses}
              onChange={setDefaultUniverses}
            />
          </Field>
          <Field label="Default strategies">
            <CheckboxGroup options={STRATEGY_OPTIONS} selected={defaultStrategies}
              onChange={setDefaultStrategies} />
          </Field>
          <RangeField label="Default forward-test gate" value={defaultGate}
            onChange={setDefaultGate} min={0} max={100} />
          <div>
            <Button variant="primary" onClick={save} loading={setPreference.isPending}>
              Save defaults
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Strategies" description="What each of S1-S4 looks for." />
        <CardBody className="space-y-2">
          {(config?.strategies ?? []).map((strategy) => (
            <div key={strategy.id}
              className="flex items-baseline gap-3 rounded-md border border-line bg-elevated
                px-3 py-2">
              <Badge tone="accent">{strategy.label}</Badge>
              <p className="text-xs text-ink">{strategy.name}</p>
            </div>
          ))}
          <Note>
            The exact rules are not paraphrased anywhere in this interface. Open any stock and
            read its condition matrix — that is the rule set the scanner actually evaluates.
          </Note>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="What this application is" />
        <CardBody className="space-y-2 text-xs leading-relaxed text-muted">
          <p>
            A research and decision-support system. It places no orders and holds no broker
            write permissions.
          </p>
          <p>
            A setup score ranks quality against the engine&apos;s own components. It is not a
            probability of profit. Historical results are research output and can be flattered by
            overfitting, survivorship bias, unrealistic execution, small samples or regime
            dependence.
          </p>
          <p>
            Validate anything important out of sample and in forward testing before acting on it.
          </p>
        </CardBody>
      </Card>
    </Page>
  );
}
