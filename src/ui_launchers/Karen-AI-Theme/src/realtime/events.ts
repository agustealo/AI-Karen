/**
 * Event validation utilities.
 */

import { EventType, RealtimeEvent } from "./types";

export function validateEvent(data: unknown): RealtimeEvent | null {
  if (!data || typeof data !== "object") return null;
  const obj = data as Record<string, unknown>;

  const event_id = obj.event_id;
  const event_type = obj.event_type;
  const tenant_id = obj.tenant_id;
  const resource_id = obj.resource_id;
  const correlation_id = obj.correlation_id;

  if (
    typeof event_id !== "string" ||
    typeof event_type !== "string" ||
    typeof tenant_id !== "string" ||
    typeof resource_id !== "string" ||
    typeof correlation_id !== "string"
  ) {
    return null;
  }

  const version = typeof obj.version === "number" ? obj.version : 1;
  const occurred_at = typeof obj.occurred_at === "string" ? obj.occurred_at : new Date().toISOString();
  const payload = typeof obj.payload === "object" && obj.payload !== null ? (obj.payload as Record<string, unknown>) : {};

  return {
    event_id,
    event_type: event_type as EventType,
    version,
    tenant_id,
    resource_id,
    correlation_id,
    occurred_at,
    payload,
  };
}

export function isSafePayload(payload: Record<string, unknown>): boolean {
  const forbidden = [
    "system_prompt",
    "private_reasoning",
    "provider_credentials",
    "internal_policy",
    "raw_authorization_state",
    "secret_metadata",
  ];
  return !forbidden.some((key) => key in payload);
}

export function matchesTopic(topic: string, event: RealtimeEvent): boolean {
  const parts = topic.split(":");
  if (parts.length !== 4) return false;
  if (parts[0] !== `tenant` || parts[1] !== event.tenant_id) return false;
  const kind = parts[2];
  if (kind === "notifications" || kind === "admin") return true;
  return parts[3] === event.resource_id;
}
