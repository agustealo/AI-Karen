import { useEffect, useMemo, useState } from "react";
import { PresenceClient } from "../presence";
import { PresenceState } from "../types";

export function getPresenceClient(): PresenceClient {
  return new PresenceClient();
}

export function usePresence() {
  const [state, setState] = useState<PresenceState | null>(null);
  const client = useMemo(getPresenceClient, []);

  useEffect(() => {
    const unsubscribe = client.subscribe(setState);
    return () => {
      unsubscribe();
      client.disconnect();
    };
  }, [client]);

  return { state, client };
}
