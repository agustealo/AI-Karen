import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import { ConnectionState } from "../types";
import { RealtimeClient } from "../client";

/** Independent compatibility instance; never reuse a previous tenant's client. */
export function getRealtimeClient(tenantId: string): RealtimeClient {
  return new RealtimeClient(tenantId);
}

export function useRealtimeConnection(tenantId: string) {
  const client = useMemo(() => getRealtimeClient(tenantId), [tenantId]);
  const subscribe = useCallback((notify: () => void) => client.onStateChange(notify), [client]);
  const snapshot = useCallback(() => client.connectionState, [client]);
  const state = useSyncExternalStore<ConnectionState>(subscribe, snapshot, () => "disconnected");

  useEffect(() => {
    client.connect();
    return () => client.disconnect();
  }, [client]);

  return { state, client };
}
