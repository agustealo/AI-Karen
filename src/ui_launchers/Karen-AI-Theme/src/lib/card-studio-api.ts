"use client";

/**
 * The Card Studio client is a typed adapter to the canonical authenticated
 * API. No local template store, policy grant, data source or renderer exists.
 * This module only handles inert definitions and verified commit receipts.
 */
import { z } from "zod";
import apiClient, { ApiError } from "@/lib/api";

export { ApiError };

const slug = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;
const slotKey = /^[a-z][a-z0-9_]*$/;
const controlOrMarkup = /[\u0000-\u001f\u007f<>]/;

const slotSchema = z.object({
  slot_id: z.string().min(1).max(32).regex(slotKey),
  component_type: z.string().min(1).max(80),
}).strict();

export const cardDefinitionSchema = z.object({
  schema_version: z.literal(1),
  template_key: z.string().min(1).max(64).regex(slug),
  title: z.string().trim().min(1).max(100).refine(value => !controlOrMarkup.test(value)),
  description: z.string().trim().min(1).max(240)
    .refine(value => !controlOrMarkup.test(value)).optional(),
  layout: z.enum(["stack", "grid"]),
  density: z.enum(["compact", "comfortable"]),
  interaction_mode: z.literal("read_only"),
  slots: z.array(slotSchema).min(1).max(6),
}).strict().superRefine((draft, ctx) => {
  const ids = draft.slots.map(slot => slot.slot_id);
  if (new Set(ids).size !== ids.length) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: "Duplicate slot identifier" });
  }
  if (new TextEncoder().encode(JSON.stringify(draft)).byteLength > 4096) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: "Template exceeds the size limit" });
  }
});
export type CardDefinition = z.infer<typeof cardDefinitionSchema>;
export type CardSlot = CardDefinition["slots"][number];

const savedSchema = z.object({
  template_id: z.string().uuid(),
  template_key: z.string().min(1).max(64),
  revision: z.number().int().positive(),
  lifecycle: z.enum(["draft", "archived"]),
  definition: cardDefinitionSchema,
}).strict();
export type SavedCardTemplate = z.infer<typeof savedSchema>;

const catalogEntrySchema = z.object({
  origin: z.literal("system"),
  editable: z.literal(false),
  definition: cardDefinitionSchema,
}).strict();
export type CatalogEntry = z.infer<typeof catalogEntrySchema>;

const catalogSchema = z.object({
  schema_version: z.literal(1),
  catalog: z.array(catalogEntrySchema).min(1).max(20),
}).strict();

const librarySchema = z.object({
  schema_version: z.literal(1),
  templates: z.array(savedSchema).max(50),
}).strict();

const receiptSchema = z.object({
  idempotency_key: z.string().uuid(),
  operation: z.enum(["create", "revise", "archive"]),
  template_id: z.string().uuid(),
  revision: z.number().int().positive(),
}).strict();
const committedSchema = z.object({
  schema_version: z.literal(1),
  committed: z.literal(true),
  template: savedSchema,
  receipt: receiptSchema,
}).strict();

export type CardMutation =
  | { operation: "create"; idempotency_key: string; draft: CardDefinition }
  | { operation: "revise"; idempotency_key: string; template_id: string; expected_revision: number; draft: CardDefinition }
  | { operation: "archive"; idempotency_key: string; template_id: string; expected_revision: number };

export class CardStudioProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CardStudioProtocolError";
  }
}

export function validateCardDefinition(
  raw: unknown, catalog: readonly CatalogEntry[],
): CardDefinition {
  const draft = cardDefinitionSchema.safeParse(raw);
  if (!draft.success) {
    throw new CardStudioProtocolError("Draft fields do not satisfy the bounded template contract.");
  }
  const allowed = new Set(catalog.flatMap(entry =>
    entry.definition.slots.map(slot => slot.component_type),
  ));
  if (!draft.data.slots.every(slot => allowed.has(slot.component_type))) {
    throw new CardStudioProtocolError("A slot names an unsupported host component.");
  }
  return draft.data;
}

export function createBlankCardDraft(catalog: readonly CatalogEntry[]): CardDefinition {
  const component = catalog[0]?.definition.slots[0]?.component_type;
  if (!component) {
    throw new CardStudioProtocolError("No authorized components were returned.");
  }
  return {
    schema_version: 1,
    template_key: "",
    title: "",
    layout: "stack",
    density: "comfortable",
    interaction_mode: "read_only",
    slots: [{ slot_id: "primary", component_type: component }],
  };
}

export async function listCardStudioCatalog(): Promise<CatalogEntry[]> {
  const result = catalogSchema.safeParse(
    await apiClient.get<unknown>("/api/chat/card-studio/catalog"),
  );
  if (!result.success) {
    throw new CardStudioProtocolError("Host Card Studio catalog is unavailable or invalid.");
  }
  return result.data.catalog;
}

export async function listSavedCardTemplates(): Promise<SavedCardTemplate[]> {
  const parsed = librarySchema.safeParse(
    await apiClient.get<unknown>("/api/chat/card-studio/templates?limit=50&include_archived=true"),
  );
  if (!parsed.success) {
    throw new CardStudioProtocolError("Saved Card Studio inventory was not verified.");
  }
  return parsed.data.templates;
}

function committedMatchesRequest(
  request: CardMutation,
  value: z.infer<typeof committedSchema>,
): boolean {
  if (value.receipt.operation !== request.operation ||
      value.receipt.idempotency_key !== request.idempotency_key ||
      value.receipt.template_id !== value.template.template_id ||
      value.receipt.revision !== value.template.revision) return false;
  if (request.operation === "create") {
    if (value.template.revision !== 1 || value.template.lifecycle !== "draft") return false;
  } else if (value.template.template_id !== request.template_id) return false;
  if (request.operation === "revise" &&
      (value.template.revision !== request.expected_revision + 1 ||
       value.template.lifecycle !== "draft")) return false;
  if (request.operation === "archive" &&
      (value.template.revision !== request.expected_revision ||
       value.template.lifecycle !== "archived")) return false;
  if (request.operation !== "archive") {
    const expected = request.draft;
    const saved = value.template.definition;
    return expected.template_key === saved.template_key &&
      expected.title === saved.title &&
      (expected.description ?? "") === (saved.description ?? "") &&
      expected.layout === saved.layout &&
      expected.density === saved.density &&
      expected.interaction_mode === saved.interaction_mode &&
      JSON.stringify(expected.slots) === JSON.stringify(saved.slots);
  }
  return true;
}

/**
 * One HTTP mutation attempt. Uncertain failures are intentionally NOT retried.
 * Consumers must retain the original request and reuse its key and immutable
 * payload for a deliberate, user-triggered replay.
 */
export async function submitCardMutation(
  request: CardMutation,
): Promise<SavedCardTemplate> {
  const body = request.operation === "archive"
    ? { idempotency_key: request.idempotency_key, expected_revision: request.expected_revision }
    : request.operation === "revise"
      ? { idempotency_key: request.idempotency_key, expected_revision: request.expected_revision, draft: request.draft }
      : { idempotency_key: request.idempotency_key, draft: request.draft };
  const route = request.operation === "create"
    ? "/api/chat/card-studio/templates"
    : request.operation === "archive"
      ? `/api/chat/card-studio/templates/${request.template_id}/archive`
      : `/api/chat/card-studio/templates/${request.template_id}`;
  const unverified = request.operation === "revise"
    ? await apiClient.put<unknown>(route, body)
    : await apiClient.post<unknown>(route, body);
  const parsed = committedSchema.safeParse(unverified);
  if (!parsed.success || !committedMatchesRequest(request, parsed.data)) {
    throw new CardStudioProtocolError(
      "The server response did not prove the requested mutation committed.",
    );
  }
  return parsed.data.template;
}

export function cardStudioErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401: return "Session expired. Sign in again; no new save was attempted.";
      case 403: return "Card Studio permission denied. Your draft is unchanged.";
      case 404: return "Card Studio is unavailable or this template is no longer accessible.";
      case 409: return "A concurrent revision or template key conflict was detected. Reload before editing.";
      case 422: return "The backend rejected this draft. Review its fields and slots.";
      default: return "Save outcome is unverified. You may retry the identical request safely.";
    }
  }
  if (error instanceof CardStudioProtocolError) return error.message;
  return "Connection failed or commit receipt is unverified. The original request can be retried.";
}
