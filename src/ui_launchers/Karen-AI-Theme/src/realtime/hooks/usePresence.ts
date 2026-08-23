import { useEffect, useRef, useState } from "react";
import { PresenceClient } from "../presence";
import { PresenceState } from "../types";

let globalPresence: PresenceClient | null = null;

export function getPresenceClient(): PresenceClient {
  if (!globalPresence) {
    globalPresence = new PresenceClient();
  }
  return globalPresence;
}

export function usePresence() {
  const [state, setState] = useState<PresenceState | null>(null);
  const clientRef = useRef(getPresenceClient());

  useEffect(() => {
    const client = clientRef.current;
    const unsub = client.subscribe(setState);
    return unsub;
  }, []);

  return { state, client: clientRef.current };
}
