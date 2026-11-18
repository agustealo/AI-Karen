/** Canonical read-only Medusa specialist discovery payload. No execution grants. */
export interface AgentCatalogRecord {
  agent_id: string;
  name: string;
  lifecycle_state: string;
  healthy: boolean;
  eligibility: "runtime_decided_per_request";
}

export interface AgentCatalogResponse {
  agents: AgentCatalogRecord[];
  total: number;
  selection_authority: string;
  execution_authority: string;
  orchestrator: string;
  eligibility_verified: false;
}

export function isAgentCatalogResponse(value: unknown): value is AgentCatalogResponse {
  if (typeof value !== "object" || value === null) return false;
  const response = value as Record<string, unknown>;
  if (!Array.isArray(response.agents) || typeof response.total !== "number") return false;
  if (
    response.total !== response.agents.length ||
    response.eligibility_verified !== false ||
    response.selection_authority !== "cortex_runtime_policy" ||
    response.execution_authority !== "chat_runtime" ||
    response.orchestrator !== "agent_medusa"
  ) return false;
  return response.agents.every((record: unknown) => {
    if (typeof record !== "object" || record === null) return false;
    const agent = record as Record<string, unknown>;
    return (
      typeof agent.agent_id === "string" &&
      agent.agent_id.length > 0 &&
      typeof agent.name === "string" &&
      typeof agent.lifecycle_state === "string" &&
      typeof agent.healthy === "boolean" &&
      agent.eligibility === "runtime_decided_per_request"
    );
  });
}

