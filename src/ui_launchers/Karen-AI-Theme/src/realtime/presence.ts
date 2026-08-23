/**
 * Frontend Presence abstraction.
 *
 * Presence is strictly for ephemeral awareness.
 */

import { PresenceState } from "./types";

export type PresenceHandler = (state: PresenceState) => void;

export class PresenceClient {
  private handlers: Set<PresenceHandler> = new Set();
  private current: PresenceState | null = null;

  subscribe(handler: PresenceHandler): () => void {
    this.handlers.add(handler);
    if (this.current) handler(this.current);
    return () => this.handlers.delete(handler);
  }

  update(state: PresenceState): void {
    this.current = state;
    this.handlers.forEach((h) => h(state));
  }

  disconnect(): void {
    this.current = null;
    this.handlers.clear();
  }
}
