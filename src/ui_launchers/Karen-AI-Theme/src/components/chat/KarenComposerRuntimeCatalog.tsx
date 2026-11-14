"use client";

import { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { isRuntimeProviderOperational } from "@/lib/model-runtime-inventory";
import type {
  RuntimeProviderCatalogProvider,
  RuntimeProviderCatalogResponse,
  RuntimeProviderCatalogModel,
} from "@/lib/model-runtime-inventory";

/**
 * Display readiness is derived from the backend's observed catalog. An
 * untested provider is never silently treated as an executable option.
 */
export function getRuntimeProviderStatusLabel(provider: RuntimeProviderCatalogProvider): string {
  if (provider.enabled === false) return "Disabled";
  if (provider.configured === false) return "Not configured";
  const status = provider.health?.status ?? "unknown";
  if (status === "unknown") return "Not checked";
  if (status === "degraded") return "Degraded";
  if (status === "unavailable") return "Unavailable";
  if (status === "unhealthy") return "Unhealthy";
  if (status !== "healthy" || provider.healthy !== true) return "Unverified";
  const available = (provider.models ?? []).filter((model) => model.available === true).length;
  return `${available} available models`;
}

export type ComposerModelRequest = { provider: string; model: string } | null;

function isSelectableProvider(provider: RuntimeProviderCatalogProvider): boolean {
  return provider.enabled === true &&
    provider.allowed_for_current_user !== false &&
    provider.configured === true &&
    isRuntimeProviderOperational(provider);
}

function selectableModels(provider: RuntimeProviderCatalogProvider | undefined): RuntimeProviderCatalogModel[] {
  if (!provider || !isSelectableProvider(provider)) return [];
  return (provider.models ?? []).filter(
    (model) => typeof model.id === "string" && model.id.length > 0 && model.available === true,
  );
}

/** A personal request, never an execution grant or a global provider mutation. */
export function KarenComposerRuntimeCatalog({
  selection,
  onSelectionChange,
  onOpenAgents,
  onOpenProviders,
}: {
  selection: ComposerModelRequest;
  onSelectionChange: (selection: ComposerModelRequest) => void;
  onOpenAgents?: () => void;
  onOpenProviders?: () => void;
}) {
  const [catalog, setCatalog] = useState<RuntimeProviderCatalogResponse | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const [browsedProvider, setBrowsedProvider] = useState("");
  const [agents, setAgents] = useState<Array<{
    agent_id: string;
    name: string;
    lifecycle_state: string;
    healthy: boolean;
  }>>([]);
  const [agentCatalogError, setAgentCatalogError] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setLoadError(false);
    apiClient.getRuntimeProviderCatalog()
      .then((data) => {
        if (cancelled) return;
        if (!data || !Array.isArray(data.providers)) throw new Error("Invalid catalog");
        setCatalog(data);
      })
      .catch(() => {
        if (!cancelled) {
          setCatalog(null);
          setLoadError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => { cancelled = true; };
  }, [refreshGeneration]);

  useEffect(() => {
    if (selection?.provider) setBrowsedProvider(selection.provider);
  }, [selection?.provider]);

  useEffect(() => {
    if (!catalog || catalog.catalog_version === "bootstrap" || !selection) return;
    const selected = catalog.providers.find((provider) => provider.id === selection.provider);
    if (!selectableModels(selected).some((model) => model.id === selection.model)) {
      // An inventory change must not leave an obsolete per-message request
      // silently attached to the next CopilotKit run.
      onSelectionChange(null);
    }
  }, [catalog, selection, onSelectionChange]);

  useEffect(() => {
    if (!showAdvanced) return;
    let cancelled = false;
    setAgentCatalogError(false);
    apiClient.get<{ agents: Array<{
      agent_id: string;
      name: string;
      lifecycle_state: string;
      healthy: boolean;
    }> }>("/api/agent-runtime/catalog")
      .then((data) => {
        if (cancelled) return;
        if (!data || !Array.isArray(data.agents)) throw new Error("Invalid agent catalog");
        setAgents(data.agents.filter(
          (agent) => typeof agent.agent_id === "string" && typeof agent.name === "string",
        ));
      })
      .catch(() => { if (!cancelled) setAgentCatalogError(true); });
    return () => { cancelled = true; };
  }, [showAdvanced]);

  const providers = useMemo(
    () => (catalog?.providers ?? []).filter((provider) =>
      provider.allowed_for_current_user !== false &&
      typeof provider.id === "string" && provider.id.length > 0,
    ),
    [catalog],
  );
  const displayedProvider = providers.find((provider) => provider.id === browsedProvider);
  const models = selectableModels(displayedProvider);
  const hasSelectableModels = providers.some((provider) => selectableModels(provider).length > 0);
  const validCatalog = Boolean(catalog && catalog.catalog_version !== "bootstrap");
  const modelValue = selection?.provider === browsedProvider &&
    models.some((model) => model.id === selection.model)
    ? selection.model : "";

  return (
    <section aria-label="Runtime provider discovery" className="min-w-0 space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[150px] flex-1 sm:max-w-[260px]">
          <label htmlFor="karen-provider-request" className="mb-1 block text-xs font-medium text-muted-foreground">
            Provider
          </label>
          <select
            id="karen-provider-request"
            aria-label="Requested model provider"
            value={browsedProvider}
            disabled={!validCatalog || isLoading}
            onChange={(event) => {
              setBrowsedProvider(event.target.value);
              onSelectionChange(null);
            }}
            className="h-10 w-full rounded-lg border border-input bg-background px-2 text-sm"
          >
            <option value="">Automatic routing (Karen default)</option>
            {providers.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.label} · {getRuntimeProviderStatusLabel(provider)}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[150px] flex-1 sm:max-w-[280px]">
          <label htmlFor="karen-model-request" className="mb-1 block text-xs font-medium text-muted-foreground">
            Model
          </label>
          <select
            id="karen-model-request"
            aria-label="Requested model"
            value={modelValue}
            disabled={!validCatalog || isLoading || models.length === 0}
            onChange={(event) => {
              const model = event.target.value;
              if (!model || !displayedProvider ||
                  !models.some((entry) => entry.id === model)) {
                onSelectionChange(null);
                return;
              }
              onSelectionChange({ provider: displayedProvider.id, model });
            }}
            className="h-10 w-full rounded-lg border border-input bg-background px-2 text-sm disabled:opacity-60"
          >
            <option value="">{browsedProvider ? "Select an available model" : "Karen chooses automatically"}</option>
            {models.map((model) => (
              <option key={model.id} value={model.id}>{model.label || model.id}</option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={() => setRefreshGeneration((generation) => generation + 1)}
          disabled={isLoading}
          className="min-h-10 rounded-lg border border-input px-3 text-xs font-medium hover:bg-muted disabled:opacity-50"
        >
          {isLoading ? "Checking…" : "Refresh models"}
        </button>
        {onOpenProviders && (
          <button
            type="button"
            onClick={onOpenProviders}
            className="min-h-10 rounded-lg border border-input px-3 text-xs font-medium hover:bg-muted"
          >
            Configure providers
          </button>
        )}
      </div>

      {loadError || !validCatalog ? (
        <p role="status" className="text-xs text-muted-foreground">
          Runtime provider catalog unavailable. No provider selection was changed.
        </p>
      ) : !hasSelectableModels ? (
        <p role="status" className="text-xs text-muted-foreground">
          No selectable models are verified. Configure a provider or local runtime, then refresh models.
          Automatic routing remains the default; it does not guarantee an available executor.
        </p>
      ) : displayedProvider && models.length === 0 ? (
        <p role="status" className="text-xs text-muted-foreground">
          {displayedProvider.label}: {getRuntimeProviderStatusLabel(displayedProvider)}.
          This provider cannot be requested until an available model is reported.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          {selection
            ? `Requested: ${displayedProvider?.label || selection.provider} / ${selection.model}. Karen reports the actual model after execution.`
            : "Automatic lets Karen choose an available model. Your preference may change if a model is unavailable."}
        </p>
      )}

      {validCatalog && (
        <details
          onToggle={(event) => setShowAdvanced(event.currentTarget.open)}
          className="rounded-lg border border-border/60 px-3 py-2"
        >
          <summary className="cursor-pointer text-xs font-medium focus-visible:outline-2 focus-visible:outline-ring">
            Advanced provider and agent details
          </summary>
          {showAdvanced && (
            <div className="mt-3 space-y-3">
              <p className="text-xs text-muted-foreground">
                Provider availability and agent registration are reported by the backend.
                They do not grant execution access.
              </p>
              {providers.length === 0 ? (
                <p className="text-sm text-muted-foreground">No providers were returned for this user.</p>
              ) : (
                <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
                  {providers.map((provider) => (
                    <li key={provider.id} className="rounded-lg border border-border/60 px-2 py-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate font-medium">{provider.label}</span>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {getRuntimeProviderStatusLabel(provider)}
                        </span>
                      </div>
                      {Boolean(provider.models?.length) && (
                        <details className="mt-1 text-xs">
                          <summary className="cursor-pointer text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring">
                            View reported models
                          </summary>
                          <ul className="mt-1 space-y-1">
                            {provider.models?.map((model) => (
                              <li key={model.id} className="flex justify-between gap-2 rounded bg-muted/40 px-2 py-1">
                                <span className="min-w-0 break-all">{model.label}</span>
                                <span className="shrink-0 text-muted-foreground">
                                  {model.available === true ? "Available" :
                                    model.available === false ? "Unavailable" : "Unknown"}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <section aria-label="Registered agent discovery" className="border-t border-border/60 pt-3">
                <h4 className="text-sm font-medium">Registered agents</h4>
                <p className="text-xs text-muted-foreground">
                  Discovery only. Catalog health does not grant execution access.
                  CORTEX and RuntimePolicy decide eligibility per request.
                </p>
                {onOpenAgents && (
                  <button type="button" onClick={onOpenAgents}
                    className="min-h-11 rounded-lg border border-input px-3 text-xs font-medium hover:bg-muted">
                    Open Agents workspace
                  </button>
                )}
                {agentCatalogError ? (
                  <p role="status" className="text-xs text-muted-foreground">Agent catalog unavailable.</p>
                ) : (
                  <ul className="mt-2 space-y-1 text-xs">
                    {agents.map((agent) => (
                      <li key={agent.agent_id} className="flex justify-between gap-2 rounded border border-border/50 px-2 py-1.5">
                        <span>{agent.name}</span>
                        <span className="text-muted-foreground">
                          {agent.lifecycle_state === "active" && agent.healthy === true
                            ? "Registered and healthy; eligibility unverified" : "Not ready"}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          )}
        </details>
      )}
    </section>
  );
}
