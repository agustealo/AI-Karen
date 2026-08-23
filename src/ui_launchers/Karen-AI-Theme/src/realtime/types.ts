/**
 * Frontend realtime types.
 * Shared between client, hooks, and components.
 */

export type ConnectionState = "connecting" | "connected" | "reconnecting" | "degraded" | "disconnected";

export type EventType =
  | "conversation.message.created.v1"
  | "conversation.updated.v1"
  | "execution.started.v1"
  | "execution.progress.v1"
  | "execution.completed.v1"
  | "execution.failed.v1"
  | "artifact.upload.started.v1"
  | "artifact.available.v1"
  | "artifact.failed.v1"
  | "artifact.deleted.v1"
  | "notification.created.v1"
  | "provider.degraded.v1"
  | "provider.recovered.v1";

export interface RealtimeEvent {
  event_id: string;
  event_type: EventType;
  version: number;
  tenant_id: string;
  resource_id: string;
  correlation_id: string;
  occurred_at: string;
  payload: Record<string, unknown>;
}

export interface RealtimeSubscription {
  subscriptionId: string;
  topic: string;
  state: ConnectionState;
}

export interface PresenceState {
  user_id: string;
  session_id: string;
  status: "online" | "away" | "active";
  view?: string;
  device?: string;
}
