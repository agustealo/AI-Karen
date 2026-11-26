/** Unavailable presence compatibility boundary, not a local presence authority. */
import { PresenceState } from "./types";

export type PresenceHandler = (state: PresenceState) => void;

export class PresenceClient {
  subscribe(handler: PresenceHandler): () => void {
    // No authenticated transport or session scope: retain no private state.
    void handler;
    return () => {};
  }

  update(state: PresenceState): void {
    void state;
    throw new Error("Authenticated presence transport unavailable");
  }

  disconnect(): void {
    // There is no established presence transport to close.
  }
}
