import { describe, expect, it } from "vitest";

import { isAgentCatalogResponse } from "./agentCatalog";

const validCatalog = {
  agents: [{
    agent_id: "researcher",
    name: "Researcher",
    lifecycle_state: "active",
    healthy: true,
    eligibility: "runtime_decided_per_request",
  }],
  total: 1,
  eligibility_verified: false,
  selection_authority: "cortex_runtime_policy",
  execution_authority: "chat_runtime",
  orchestrator: "agent_medusa",
};

describe("Agent Medusa minimal discovery contract", () => {
  it("accepts a valid specialist without non-disclosed capability metadata", () => {
    expect(isAgentCatalogResponse(validCatalog)).toBe(true);
    expect(isAgentCatalogResponse({ ...validCatalog, agents: [], total: 0 })).toBe(true);
  });

  it.each([
    null,
    [],
    {},
    { ...validCatalog, agents: null },
    { ...validCatalog, agents: [{}] },
    { ...validCatalog, agents: [{ ...validCatalog.agents[0], healthy: "true" }] },
    { ...validCatalog, agents: [{ ...validCatalog.agents[0], eligibility: "authorized" }] },
    { ...validCatalog, total: 0 },
    { ...validCatalog, eligibility_verified: true },
    { ...validCatalog, execution_authority: "browser" },
    { ...validCatalog, selection_authority: "ui" },
    { ...validCatalog, orchestrator: "legacy" },
  ])("rejects malformed or unauthorized contract shape: %o", (payload) => {
    expect(isAgentCatalogResponse(payload)).toBe(false);
  });
});
