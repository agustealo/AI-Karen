/**
 * Frontend realtime compatibility boundary.
 *
 * No authenticated transport is installed. Local descriptors are not active
 * subscriptions, and the UI must use canonical authenticated reads instead.
 */
import { ConnectionState, RealtimeEvent, RealtimeSubscription } from "./types";
import { TopicRegistry } from "./topics";

type EventHandler = (event: RealtimeEvent) => void;
type ErrorHandler = (error: Error) => void;
type StateChangeHandler = (prev: ConnectionState, next: ConnectionState) => void;

export class RealtimeClient {
  private state: ConnectionState = "disconnected";
  private errorHandlers = new Set<ErrorHandler>();
  private stateHandlers = new Set<StateChangeHandler>();
  private topicRegistry: TopicRegistry;

  constructor(tenantId: string) {
    this.topicRegistry = new TopicRegistry(tenantId);
  }

  get connectionState(): ConnectionState {
    return this.state;
  }

  get activeSubscriptions(): RealtimeSubscription[] {
    return [];
  }

  connect(): void {
    // No timer, fabricated handshake, or optimistic connection state.
    this.setState("degraded");
  }

  disconnect(): void {
    this.setState("disconnected");
  }

  subscribe(topicOrFactory: string | ((registry: TopicRegistry) => string), handler: EventHandler): RealtimeSubscription {
    const topic = typeof topicOrFactory === "function" ? topicOrFactory(this.topicRegistry) : topicOrFactory;
    const resolved = this.topicRegistry.resolve(topic);
    if (!resolved) {
      throw new Error("Invalid realtime topic for this tenant");
    }
    // Preserve the compatibility descriptor without retaining a callback or
    // pretending that a remote subscription has been authorized.
    void handler;
    return { subscriptionId: `sub-${crypto.randomUUID()}`, topic: resolved, state: this.state };
  }

  unsubscribe(subscriptionId: string): void {
    // There is no active remote subscription to cancel.
    void subscriptionId;
  }

  onError(handler: ErrorHandler): () => void {
    this.errorHandlers.add(handler);
    return () => { this.errorHandlers.delete(handler); };
  }

  onStateChange(handler: StateChangeHandler): () => void {
    this.stateHandlers.add(handler);
    return () => { this.stateHandlers.delete(handler); };
  }

  /** @deprecated Synthetic events are never consumer delivery evidence. */
  simulateIncoming(raw: unknown): void {
    void raw;
    this.errorHandlers.forEach((handler) => handler(new Error("Authenticated realtime transport unavailable")));
  }

  private setState(next: ConnectionState): void {
    const prev = this.state;
    if (prev === next) return;
    this.state = next;
    this.stateHandlers.forEach((handler) => handler(prev, next));
  }
}
