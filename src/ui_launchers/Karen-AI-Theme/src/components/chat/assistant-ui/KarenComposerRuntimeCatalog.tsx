"use client";
import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import type { RuntimeProviderCatalogResponse } from "@/lib/model-runtime-inventory";

/** A request hint only: backend validates every model selection. */
export function KarenComposerRuntimeCatalog({ selectedProvider, selectedModel, onSelectionChange }: {
  selectedProvider: string;
  selectedModel: string;
  onSelectionChange: (provider: string, model: string) => void;
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
      .then((result) => {
        if (!cancelled) {
          if (!Array.isArray(result.agents)) throw new Error("Invalid agent catalog");
          setAgents(result.agents);
        }
      })
      .catch(() => { if (!cancelled) setAgentCatalogError(true); });
    return () => { cancelled = true; };
  }, []);
  if (error) return <p role="status" className="text-sm text-muted-foreground">Runtime catalog unavailable. No provider selection was changed.</p>;
  if (!catalog) return <p role="status" className="text-sm text-muted-foreground">Loading runtime providers…</p>;
  const providers = catalog.providers.filter((provider) => provider.enabled === true && provider.allowed_for_current_user !== false);
  return <section aria-label="Runtime provider discovery" className="space-y-2">
    <h4 className="text-sm font-medium">Providers and models</h4>
    <p className="text-xs text-muted-foreground">Select a runtime-reported provider and model, or use automatic routing. The backend remains authoritative.</p>
    <label htmlFor="karen-chat-provider" className="block font-medium">Provider</label>
    <select id="karen-chat-provider" value={selectedProvider} onChange={(event) => onSelectionChange(event.target.value, "")} className="w-full rounded-md border border-input bg-background p-2">
      <option value="">Automatic (runtime default)</option>
      {providers.filter((provider) => provider.configured !== false && provider.healthy !== false).map((provider) =>
        <option key={provider.id} value={provider.id}>{provider.label}</option>)}
    </select>
    {selectedProvider && <>
      <label htmlFor="karen-chat-model" className="block font-medium">Model</label>
      <select id="karen-chat-model" value={selectedModel} onChange={(event) => onSelectionChange(selectedProvider, event.target.value)} className="w-full rounded-md border border-input bg-background p-2">
        <option value="">Provider default</option>
        {(providers.find((provider) => provider.id === selectedProvider)?.models || [])
          .filter((model) => model.available === true)
          .map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}
      </select>
    </>}
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
    <div className="mt-3 border-t border-border/60 pt-2">
      <h4 className="text-sm font-medium">Registered agents</h4>
      <p className="text-xs text-muted-foreground">Discovery only. These are catalog entries, not authorized execution choices. RuntimePolicy eligibility and Medusa routing must be verified before an agent selector can be enabled.</p>
      {agentCatalogError ? <p role="status" className="text-xs text-muted-foreground">Agent catalog unavailable.</p> :
        <ul className="mt-1 space-y-1 text-xs">{agents.map((agent) =>
          <li key={agent.agent_id} className="flex justify-between gap-2">
            <span>{agent.name}</span>
            <span className="text-muted-foreground">{agent.lifecycle_state === "active" && agent.healthy ? "Catalog healthy; eligibility unverified" : "Not ready"}</span>
          </li>)}</ul>}
    </div>
  </section>;
}
