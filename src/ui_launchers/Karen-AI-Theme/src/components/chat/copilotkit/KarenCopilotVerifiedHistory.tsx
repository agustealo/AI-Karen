"use client";

/**
 * CopilotKit v2 assistant-message slot for backend-attested saved CUSTOM events.
 * CopilotKit owns text/toolbar/scroll/composer; existing Karen presentation
 * components own visuals. The backend alone owns execution, evidence and storage.
 */
import { CopilotChatAssistantMessage } from "@copilotkit/react-core/v2";
import { createContext, useContext } from "react";
import type { ComponentProps, ReactNode } from "react";

import {
  KarenPresentationRegistry,
  parseKarenPresentation,
  type KarenPresentationEnvelope,
} from "@/components/chat/assistant-ui/KarenPresentationRegistry";
import {
  KarenResponseIntegrity,
  KarenRestoredExecutionReceipt,
} from "@/components/chat/KarenVerifiedReceipts";

type VerifiedPart =
  | { type: "presentation"; value: KarenPresentationEnvelope }
  | { type: "receipt"; value: Record<string, unknown> }
  | { type: "integrity"; value: Record<string, unknown> };
export type VerifiedHistoryParts = ReadonlyMap<string, readonly VerifiedPart[]>;

const ALLOWED_RECEIPT = new Set([
  "requested_provider", "requested_model", "actual_provider", "actual_model",
  "response_source", "runtime_engine", "degradation_reason",
  "degraded_mode", "fallback_level",
]);
const ALLOWED_INTEGRITY = new Set([
  "output_truncated", "cortex_intent", "personal_recall_grounded", "evidence_source",
]);

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validReceipt(value: unknown): value is Record<string, unknown> {
  if (!record(value) || Object.keys(value).some(key => !ALLOWED_RECEIPT.has(key))) return false;
  for (const key of ["actual_provider", "actual_model", "response_source"]) {
    if (typeof value[key] !== "string" ||
        !(value[key] as string).trim() || (value[key] as string).length > 200) return false;
  }
  for (const [key, val] of Object.entries(value)) {
    if (["degraded_mode", "fallback_level"].includes(key)) continue;
    if (typeof val !== "string" || val.length > 200) return false;
  }
  return (value.degraded_mode === undefined || value.degraded_mode === true) &&
    (value.fallback_level === undefined ||
      (typeof value.fallback_level === "number" &&
       Number.isInteger(value.fallback_level) && value.fallback_level >= 0 &&
       value.fallback_level <= 100));
}

function validIntegrity(value: unknown): value is Record<string, unknown> {
  if (!record(value) || Object.keys(value).some(key => !ALLOWED_INTEGRITY.has(key))) return false;
  if (typeof value.output_truncated !== "boolean") return false;
  if (value.cortex_intent !== undefined && value.cortex_intent !== "memory.recall") return false;
  if (value.personal_recall_grounded !== undefined &&
      typeof value.personal_recall_grounded !== "boolean") return false;
  if (value.evidence_source !== undefined &&
      !["authorized_memory_evidence", "authorized_conversation_evidence"].includes(
        String(value.evidence_source))) return false;
  return value.output_truncated === true ||
    (value.cortex_intent === "memory.recall" &&
     typeof value.personal_recall_grounded === "boolean");
}

/**
 * Validate the complete backend-owned snapshot BEFORE SDK agent.setMessages().
 * Unknown events, duplicate receipts, unbound IDs and unsupported presentation
 * versions are hard errors. No "best-effort" partial transcript playback.
 */
export function parseKarenVerifiedHistory(
  value: unknown, messages: ReadonlyArray<{ id: string; role: string }>,
): VerifiedHistoryParts {
  if (!Array.isArray(value) || value.length > 500 * 8) {
    throw new Error("Unsupported verified conversation events");
  }
  const assistantIds = new Set(messages.filter(m => m.role === "assistant").map(m => m.id));
  const parts = new Map<string, VerifiedPart[]>();
  const counters = new Map<string, {
    presentation: number; receipt: number; integrity: number;
    presentationIds: Set<string>;
  }>();
  for (const candidate of value) {
    if (!record(candidate) || Object.keys(candidate).some(
      key => !["type", "name", "messageId", "value"].includes(key)
    ) || candidate.type !== "CUSTOM" || typeof candidate.messageId !== "string" ||
      !assistantIds.has(candidate.messageId) || !record(candidate.value)) {
      throw new Error("Unsupported verified conversation event");
    }
    const name = candidate.name;
    const id = candidate.messageId;
    const seen = counters.get(id) || {
      presentation: 0, receipt: 0, integrity: 0,
      presentationIds: new Set<string>(),
    };
    let part: VerifiedPart;
    if (name === "karen.presentation.v1") {
      const envelope = parseKarenPresentation(candidate.value);
      if (!envelope || ++seen.presentation > 6 ||
          seen.presentationIds.has(envelope.presentation_id)) {
        throw new Error("Unsupported verified presentation");
      }
      seen.presentationIds.add(envelope.presentation_id);
      part = { type: "presentation", value: envelope };
    } else if (name === "karen.execution_receipt.v1") {
      if (!validReceipt(candidate.value) || ++seen.receipt > 1) {
        throw new Error("Unsupported verified execution receipt");
      }
      part = { type: "receipt", value: candidate.value };
    } else if (name === "karen.response_integrity.v1") {
      if (!validIntegrity(candidate.value) || ++seen.integrity > 1) {
        throw new Error("Unsupported verified response integrity");
      }
      part = { type: "integrity", value: candidate.value };
    } else {
      throw new Error("Unsupported verified conversation event");
    }
    counters.set(id, seen);
    parts.set(id, [...(parts.get(id) || []), part]);
  }
  return parts;
}

const VerifiedHistoryContext = createContext<VerifiedHistoryParts>(new Map());

export function KarenVerifiedHistoryProvider({
  parts, children,
}: { parts: VerifiedHistoryParts; children: ReactNode }) {
  return (
    <VerifiedHistoryContext.Provider value={parts}>
      {children}
    </VerifiedHistoryContext.Provider>
  );
}

/**
 * Read-only projection of the most recent backend-validated execution receipt.
 * Never infer execution from a requested model, agent state or an empty event.
 */
export function useKarenLatestVerifiedExecution(): Record<string, unknown> | null {
  const verified = useContext(VerifiedHistoryContext);
  let latest: Record<string, unknown> | null = null;
  for (const parts of verified.values()) {
    for (const part of parts) {
      if (part.type === "receipt") latest = part.value;
    }
  }
  return latest;
}

/** Preserve the SDK's default assistant message (including its toolbar). */
export function KarenCopilotAssistantMessage(
  props: ComponentProps<typeof CopilotChatAssistantMessage>,
) {
  const parts = useContext(VerifiedHistoryContext).get(props.message.id) || [];
  return (
    <div data-testid="karen-copilot-assistant-message" className="min-w-0">
      <CopilotChatAssistantMessage {...props} />
      {parts.map((part, index) => (
        <div key={index} data-testid="karen-copilot-verified-part">
          {part.type === "presentation" &&
            <KarenPresentationRegistry data={part.value} />}
          {part.type === "receipt" &&
            <KarenRestoredExecutionReceipt data={part.value} />}
          {part.type === "integrity" &&
            <KarenResponseIntegrity data={part.value} />}
        </div>
      ))}
    </div>
  );
}

/** CopilotKit v2 slots require the default component's static slot namespace. */
export const KarenCopilotAssistantSlot = Object.assign(
  KarenCopilotAssistantMessage, CopilotChatAssistantMessage,
);
