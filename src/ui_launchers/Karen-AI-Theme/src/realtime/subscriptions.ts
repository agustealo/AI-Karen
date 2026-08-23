/**
 * Subscription management for frontend.
 */

import { RealtimeEvent, RealtimeSubscription } from "./types";
import { RealtimeClient } from "./client";

export type Listener = (event: RealtimeEvent) => void;

export function subscribeToConversation(
  client: RealtimeClient,
  conversationId: string,
  handler: Listener,
): RealtimeSubscription {
  return client.subscribe(
    (registry) => registry.conversation(conversationId),
    handler,
  );
}

export function subscribeToExecution(
  client: RealtimeClient,
  executionId: string,
  handler: Listener,
): RealtimeSubscription {
  return client.subscribe(
    (registry) => registry.execution(executionId),
    handler,
  );
}

export function subscribeToNotifications(
  client: RealtimeClient,
  handler: Listener,
): RealtimeSubscription {
  return client.subscribe((registry) => registry.notifications(), handler);
}

export function subscribeToUser(
  client: RealtimeClient,
  userId: string,
  handler: Listener,
): RealtimeSubscription {
  return client.subscribe((registry) => registry.user(userId), handler);
}
