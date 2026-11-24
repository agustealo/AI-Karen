"use client";

import { useEffect, useId, useState } from "react";
import { Wrench } from "lucide-react";
import { apiClient } from "@/lib/api";

type Agent = { agent_id: string; name: string; lifecycle_state: string; healthy: boolean };
type Discovery =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "ready"; agents: Agent[] };

function parseAgents(value: unknown): Agent[] {
  if (!value || typeof value !== "object" || !("agents" in value) || !Array.isArray(value.agents)) {
    throw new Error("Invalid agent catalog");
  }
  const ids = new Set<string>();
  return value.agents.map((entry: unknown) => {
    if (!entry || typeof entry !== "object") throw new Error("Invalid agent");
    const agent = entry as Partial<Agent>;
    if (typeof agent.agent_id !== "string" || !agent.agent_id.trim() ||
        typeof agent.name !== "string" || !agent.name.trim() ||
        typeof agent.lifecycle_state !== "string" || typeof agent.healthy !== "boolean" ||
        ids.has(agent.agent_id)) throw new Error("Invalid agent");
    ids.add(agent.agent_id);
    return { agent_id: agent.agent_id, name: agent.name, lifecycle_state: agent.lifecycle_state, healthy: agent.healthy };
  });
}

/** Read-only discovery. Neither catalog health nor navigation authorizes execution. */
function AgentDiscoveryPanel({ onOpenAgents, disabled }: { onOpenAgents: () => void; disabled: boolean }) {
  const [state, setState] = useState<Discovery>({ kind: "loading" });
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    let cancelled = false;
    apiClient.get<unknown>("/api/agent-runtime/catalog")
      .then(parseAgents)
      .then(agents => { if (!cancelled) setState({ kind: "ready", agents }); })
      .catch(() => { if (!cancelled) setState({ kind: "unavailable" }); });
    return () => { cancelled = true; };
  }, [generation]);

  return <section aria-label="Registered agent discovery" className="space-y-2">
    <p className="text-xs text-muted-foreground">
      Discovery only. Catalog health does not grant execution access.
      CORTEX and RuntimePolicy decide eligibility per request.
    </p>
    {state.kind === "loading" ? <p role="status" className="text-xs">Checking agent catalog…</p>
      : state.kind === "unavailable" ? <p role="status" className="text-xs">Agent catalog unavailable.</p>
      : state.agents.length === 0 ? <p className="text-xs">No agents were returned.</p>
      : <ul className="max-h-32 space-y-1 overflow-y-auto text-xs">
        {state.agents.map(agent => <li key={agent.agent_id} className="flex flex-wrap justify-between gap-2 rounded border border-border/50 px-2 py-1.5">
          <span className="break-all">{agent.name}</span>
          <span className="text-muted-foreground">{agent.lifecycle_state === "active" && agent.healthy
            ? "Registered and healthy; eligibility unverified" : "Not ready"}</span>
        </li>)}
      </ul>}
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={state.kind === "loading"} onClick={() => {
        setState({ kind: "loading" });
        setGeneration(value => value + 1);
      }} className="min-h-11 rounded-lg border border-input px-3 text-xs disabled:opacity-50">Refresh agents</button>
      <button type="button" disabled={disabled} onClick={onOpenAgents}
        className="min-h-11 rounded-lg border border-input px-3 text-xs disabled:opacity-50">Open Agents workspace</button>
    </div>
  </section>;
}

export function KarenComposerAgentDiscovery({ onOpenAgents, disabled = false }: {
  onOpenAgents: () => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return <div className="min-w-0 max-w-full px-3 pt-2">
    <button type="button" aria-expanded={open} aria-controls={open ? id : undefined}
      onClick={() => setOpen(value => !value)}
      className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-input px-3 text-xs font-medium focus-visible:outline-2 focus-visible:outline-ring">
      <Wrench aria-hidden="true" className="h-4 w-4" /> Discover agents
    </button>
    {open && <div id={id} className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-border/60 p-3">
      <AgentDiscoveryPanel onOpenAgents={onOpenAgents} disabled={disabled} />
    </div>}
  </div>;
}
