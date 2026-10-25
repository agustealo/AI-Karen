"use client";
import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import type { RuntimeProviderCatalogResponse } from "@/lib/model-runtime-inventory";

/** Catalog visibility is not authority to select a model or execute a run. */
export function KarenComposerRuntimeCatalog() {
  const [catalog, setCatalog] = useState<RuntimeProviderCatalogResponse | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    apiClient.getRuntimeProviderCatalog().then((data) => {
      if (cancelled) return;
      if (!data || !Array.isArray(data.providers)) throw new Error("Invalid catalog");
      setCatalog(data);
    }).catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, []);
  if (error) return <p role="status" className="text-sm text-muted-foreground">Runtime catalog unavailable. No provider selection was changed.</p>;
  if (!catalog) return <p role="status" className="text-sm text-muted-foreground">Loading runtime providers…</p>;
  const providers = catalog.providers.filter((provider) => provider.enabled === true && provider.allowed_for_current_user !== false);
  return <section aria-label="Runtime provider discovery" className="space-y-2">
    <h4 className="text-sm font-medium">Providers and models</h4>
    <p className="text-xs text-muted-foreground">Backend-reported discovery only. ChatRuntime owns execution and model routing.</p>
    {providers.length === 0 ? <p className="text-sm text-muted-foreground">No enabled providers reported.</p> :
      <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
        {providers.map((provider) => <li key={provider.id} className="rounded-lg border border-border/60 px-2 py-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className="min-w-0 truncate font-medium">{provider.label}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{provider.healthy === false ? "Unhealthy" : provider.configured === false ? "Not configured" : String((provider.models || []).filter((model) => model.available === true).length) + " available models"}</span>
          </div>
          {provider.models && provider.models.length > 0 && <details className="mt-1 text-xs">
            <summary className="cursor-pointer text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring">View reported models</summary>
            <ul className="mt-1 space-y-1">
              {provider.models.map((model) => <li key={model.id} className="flex justify-between gap-2 rounded bg-muted/40 px-2 py-1">
                <span className="min-w-0 break-all">{model.label}</span>
                <span className="shrink-0 text-muted-foreground">{model.available === true ? "Available" : model.available === false ? "Unavailable" : "Unknown"}</span>
              </li>)}
            </ul>
          </details>}
        </li>)}
      </ul>}
  </section>;
}
