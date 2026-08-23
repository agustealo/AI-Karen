/**
 * Frontend realtime client.
 *
 * UI-facing Realtime client abstraction.
 * Components should consume hooks/services, not call Supabase directly.
 */

import { ConnectionState, RealtimeEvent, RealtimeSubscription } from "./types";
import { TopicRegistry, resolveTopic } from "./topics";
import { validateEvent, isSafePayload, matchesTopic } from "./events";

type EventHandler = (event: RealtimeEvent) => void;
type ErrorHandler = (error: Error) => void;
type StateChangeHandler = (prev: ConnectionState, next: ConnectionState) => void;

export class RealtimeClient {
  private state: ConnectionState = "disconnected";
  private subscriptions: Map<string, { topic: string; handlers: Set<EventHandler> }> = new Map();
  private errorHandlers: Set<ErrorHandler> = new Set();
  private stateHandlers: Set<StateChangeHandler> = new Set();
  private topicRegistry: TopicRegistry;

  constructor(tenantId: string) {
    this.topicRegistry = new TopicRegistry(tenantId);
  }

  get connectionState(): ConnectionState {
    return this.state;
  }

  get activeSubscriptions(): RealtimeSubscription[] {
    return Array.from(this.subscriptions.entries()).map(([id, sub]) => ({
      subscriptionId: id,
      topic: sub.topic,
      state: this.state,
    }));
  }

  connect(): void {
    this.setState("connecting");
    setTimeout(() => {
      this.setState("connected");
    }, 50);
  }

  disconnect(): void {
    this.subscriptions.forEach((_, id) => this.unsubscribe(id));
    this.setState("disconnected");
  }

  subscribe(topicOrFactory: string | ((registry: TopicRegistry) => string), handler: EventHandler): RealtimeSubscription {
    const topic = typeof topicOrFactory === "function" ? topicOrFactory(this.topicRegistry) : topicOrFactory;
    const resolved = resolveTopic(topic);
    if (!resolved) {
      throw new Error(`Invalid topic: ${topic}`);
    }

    const id = `sub-${crypto.randomUUID()}`;
    this.subscriptions.set(id, { topic: resolved, handlers: new Set([handler]) });
    return { subscriptionId: id, topic: resolved, state: this.state };
  }

  unsubscribe(subscriptionId: string): void {
    this.subscriptions.delete(subscriptionId);
  }

  onError(handler: ErrorHandler): () => void {
    this.errorHandlers.add(handler);
    return () => this.errorHandlers.delete(handler);
  }

  onStateChange(handler: StateChangeHandler): () => void {
    this.stateHandlers.add(handler);
    return () => this.stateHandlers.delete(handler);
  }

  simulateIncoming(raw: unknown): void {
    const event = validateEvent(raw);
    if (!event) {
      this.notifyError(new Error("Invalid event received"));
      return;
    }
    if (!isSafePayload(event.payload)) {
      this.notifyError(new Error("Unsafe payload rejected"));
      return;
    }

    this.subscriptions.forEach((sub) => {
      if (sub.topic === `tenant:${event.tenant_id}:*` || matchesTopic(sub.topic, event)) {
        sub.handlers.forEach((h) => h(event));
      }
    });
  }

  private setState(next: ConnectionState): void {
    const prev = this.state;
    this.state = next;
    this.stateHandlers.forEach((h) => h(prev, next));
  }

  private notifyError(error: Error): void {
    this.errorHandlers.forEach((h) => h(error));
  }
}
