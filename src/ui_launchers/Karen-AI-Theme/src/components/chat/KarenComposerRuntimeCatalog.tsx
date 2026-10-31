"use client";
import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import type { RuntimeProviderCatalogResponse } from "@/lib/model-runtime-inventory";

/** Catalog visibility is not authority to select a model or execute a run. */
export type ComposerModelRequest = { provider: string; model: string } | null;
export function KarenComposerRuntimeCatalog({ selection, onSelectionChange }: {
  selection: ComposerModelRequest;
  onSelectionChange: (selection: ComposerModelRequest) => void;
}) {
  const [catalog, setCatalog] = useState<RuntimeProviderCatalogResponse | null>(null);
  const [error, setError] = useState(false);
  const [agents, setAgents] = useState<Array<{ agent_id: string; name: string; lifecycle_state: string; healthy: boolean }>>([]);
  const [agentCatalogError, setAgentCatalogError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    apiClient.getRuntimeProviderCatalog().then((data) => {
      if (cancelled) return;
      if (!data || !Array.isArray(data.providers)) throw new Error("Invalid catalog");
      setCatalog(data);
    }).catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    let cancelled = false;
    apiClient.get<{ agents: Array<{ agent_id: string; name: string; lifecycle_state: string; healthy: boolean }> }>("/api/agent-runtime/catalog")
      .then((data) => {
        if (cancelled) return;
        if (!data || !Array.isArray(data.agents)) throw new Error("Invalid agent catalog");
        setAgents(data.agents.filter((agent) => typeof agent.agent_id === "string" && typeof agent.name === "string"));
      })
      .catch(() => { if (!cancelled) setAgentCatalogError(true); });
    return () => { cancelled = true; };
  }, []);
  if (error) return <p role="status" className="text-sm text-muted-foreground">Runtime catalog unavailable. No provider selection was changed.</p>;
  if (!catalog) return <p role="status" className="text-sm text-muted-foreground">Loading runtime providers…</p>;
  const providers = catalog.providers.filter((provider) => provider.enabled === true && provider.allowed_for_current_user !== false);
  return <section aria-label="Runtime provider discovery" className="space-y-2">
    <h4 className="text-sm font-medium">Providers and models</h4>
    <label htmlFor="karen-model-request" className="block text-xs text-muted-foreground">Next message routing request</label>
    <select id="karen-model-request" aria-label="Requested provider and model"
      value={selection ? JSON.stringify([selection.provider, selection.model]) : ""}
      onChange={(event) => {
        if (!event.target.value) { onSelectionChange(null); return; }
        const [provider, model] = JSON.parse(event.target.value) as [string, string];
        const item = providers.find((entry) => entry.id === provider);
        if (!item || item.healthy !== true || item.configured !== true ||
          !item.models?.some((entry) => entry.id === model && entry.available === true)) {
          onSelectionChange(null);
          return;
        }
        onSelectionChange({ provider, model });
      }}
      className="h-10 w-full rounded-lg border border-input bg-background px-2 text-sm">
      <option value="">Automatic routing (Karen default)</option>
      {providers.filter((provider) => provider.configured === true && provider.healthy === true).map((provider) =>
        (provider.models || []).filter((model) => model.available === true).map((model) =>
          <option key={provider.id + "/" + model.id} value={JSON.stringify([provider.id, model.id])}>
            {provider.label}: {model.label}
          </option>
        )
      )}
    </select>
    {selection && <p className="text-xs text-muted-foreground">Requested only. ChatRuntime may reject or route differently under policy.</p>}
    <p className="text-xs text-muted-foreground">Options come from the backend catalog. ChatRuntime validates each execution request.</p>
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
    <section aria-label="Registered agent discovery" className="border-t border-border/60 pt-3">
      <h4 className="text-sm font-medium">Registered agents</h4>
      <p className="text-xs text-muted-foreground">Discovery only. Catalog health does not grant execution access. CORTEX and RuntimePolicy decide eligibility per request.</p>
      {agentCatalogError ? <p role="status" className="text-xs text-muted-foreground">Agent catalog unavailable.</p> :
        <ul className="mt-2 space-y-1 text-xs">{agents.map((agent) =>
          <li key={agent.agent_id} className="flex justify-between gap-2 rounded border border-border/50 px-2 py-1.5">
            <span>{agent.name}</span>
            <span className="text-muted-foreground">{agent.lifecycle_state === "active" && agent.healthy === true ? "Registered and healthy; eligibility unverified" : "Not ready"}</span>
          </li>)}</ul>}
    </section>
  </section>;
}
