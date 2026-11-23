import { beforeEach, describe, expect, it, vi } from "vitest";

const requests = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  default: requests,
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) { super(message); }
  },
}));

import {
  cardDefinitionSchema,
  createBlankCardDraft,
  listCardStudioCatalog,
  listSavedCardTemplates,
  submitCardMutation,
  validateCardDefinition,
  CardStudioProtocolError,
  type CatalogEntry,
  type CardDefinition,
} from "./card-studio-api";

const template = (): CardDefinition => ({
  schema_version: 1,
  template_key: "owned-clock",
  title: "Owned clock",
  layout: "stack",
  density: "comfortable",
  interaction_mode: "read_only",
  slots: [{ slot_id: "primary", component_type: "time.observation" }],
});
const catalog: CatalogEntry[] = [{
  origin: "system",
  editable: false,
  definition: { ...template(), template_key: "system-time-observation" },
}];
const committed = (operation: "create" | "revise" | "archive", revision = 1) => ({
  schema_version: 1,
  committed: true,
  template: {
    template_id: "55555555-5555-4555-8555-555555555555",
    template_key: "owned-clock",
    revision,
    lifecycle: operation === "archive" ? "archived" : "draft",
    definition: template(),
  },
  receipt: {
    idempotency_key: "99999999-9999-4999-8999-999999999999",
    template_id: "55555555-5555-4555-8555-555555555555",
    operation,
    revision,
  },
});

beforeEach(() => {
  requests.get.mockReset();
  requests.post.mockReset();
  requests.put.mockReset();
});

describe("Card Studio host-defined declarative contract", () => {
  it("accepts only the backend catalog of inert host types", () => {
    const valid = validateCardDefinition(template(), catalog);
    expect(valid.slots).toEqual(template().slots);
    expect(createBlankCardDraft(catalog).slots[0].component_type).toBe("time.observation");
    expect(() => validateCardDefinition({
      ...template(),
      slots: [{ slot_id: "primary", component_type: "code.artifact" }],
    }, catalog)).toThrow(CardStudioProtocolError);
    expect(() => validateCardDefinition({
      ...template(),
      slots: [{ slot_id: "primary", component_type: "surface.composition" }],
    }, catalog)).toThrow(CardStudioProtocolError);
    expect(cardDefinitionSchema.safeParse({ ...template(), evidence_ref: "forged" }).success).toBe(false);
    expect(cardDefinitionSchema.safeParse({ ...template(), slots: Array(7).fill(template().slots[0]) }).success).toBe(false);
    expect(cardDefinitionSchema.safeParse({ ...template(), title: "<script>alert(1)</script>" }).success).toBe(false);
    expect(cardDefinitionSchema.safeParse({
      ...template(), slots: [template().slots[0], template().slots[0]],
    }).success).toBe(false);
  });

  it("rejects a missing, malformed or caller-editable host catalog", async () => {
    requests.get.mockResolvedValueOnce({ schema_version: 1, catalog });
    await expect(listCardStudioCatalog()).resolves.toEqual(catalog);
    expect(requests.get).toHaveBeenCalledWith("/api/chat/card-studio/catalog");
    requests.get.mockResolvedValueOnce({
      schema_version: 1, catalog: [{ ...catalog[0], editable: true }],
    });
    await expect(listCardStudioCatalog()).rejects.toThrow(CardStudioProtocolError);
  });

  it("does not invent a saved library after a malformed backend response", async () => {
    requests.get.mockResolvedValueOnce({ schema_version: 1, templates: [] });
    await expect(listSavedCardTemplates()).resolves.toEqual([]);
    requests.get.mockResolvedValueOnce({ schema_version: 1, templates: [{ template_id: "bad" }] });
    await expect(listSavedCardTemplates()).rejects.toThrow(CardStudioProtocolError);
  });
});

describe("Card Studio verified mutations", () => {
  const key = "99999999-9999-4999-8999-999999999999";
  const id = "55555555-5555-4555-8555-555555555555";

  it("creates once with the caller-supplied idempotency key and no identity fields", async () => {
    requests.post.mockResolvedValueOnce(committed("create"));
    await expect(submitCardMutation({
      operation: "create", draft: template(), idempotency_key: key,
    })).resolves.toMatchObject({ template_id: id, revision: 1 });
    expect(requests.post).toHaveBeenCalledTimes(1);
    expect(requests.post).toHaveBeenCalledWith("/api/chat/card-studio/templates", {
      idempotency_key: key, draft: template(),
    });
  });

  it("preserves compare-and-swap revision for updates", async () => {
    requests.put.mockResolvedValueOnce(committed("revise", 2));
    await expect(submitCardMutation({
      operation: "revise", template_id: id, expected_revision: 1,
      draft: template(), idempotency_key: key,
    })).resolves.toMatchObject({ template_id: id, revision: 2 });
    expect(requests.put).toHaveBeenCalledWith(`/api/chat/card-studio/templates/${id}`, {
      expected_revision: 1, draft: template(), idempotency_key: key,
    });
  });

  it("archives only with a matching persisted receipt", async () => {
    requests.post.mockResolvedValueOnce(committed("archive", 2));
    await expect(submitCardMutation({
      operation: "archive", template_id: id, expected_revision: 2,
      idempotency_key: key,
    })).resolves.toMatchObject({ lifecycle: "archived" });
    expect(requests.post).toHaveBeenCalledWith(`/api/chat/card-studio/templates/${id}/archive`, {
      expected_revision: 2, idempotency_key: key,
    });
  });

  it.each([
    { committed: false },
    { receipt: { ...committed("create").receipt, idempotency_key: "00000000-0000-4000-8000-000000000000" } },
    { receipt: { ...committed("create").receipt, revision: 7 } },
    { template: { ...committed("create").template, definition: { ...template(), title: "Not requested" } } },
    { template: { ...committed("create").template, lifecycle: "archived" } },
  ])("never treats a malformed or mismatched response as saved", async (override) => {
    requests.post.mockResolvedValueOnce({ ...committed("create"), ...override });
    await expect(submitCardMutation({
      operation: "create", idempotency_key: key, draft: template(),
    })).rejects.toThrow(CardStudioProtocolError);
  });

  it("never retries after a transport failure", async () => {
    requests.post.mockRejectedValueOnce(new TypeError("Network disconnected"));
    await expect(submitCardMutation({
      operation: "create", idempotency_key: key, draft: template(),
    })).rejects.toThrow("Network disconnected");
    expect(requests.post).toHaveBeenCalledTimes(1);
  });
});
