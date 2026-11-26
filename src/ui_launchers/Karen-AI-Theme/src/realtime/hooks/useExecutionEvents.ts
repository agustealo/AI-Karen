import { useEffect, useMemo, useState } from "react";
import { RealtimeEvent } from "../types";
import { RealtimeClient } from "../client";
import { getRealtimeClient } from "./useRealtimeConnection";
import { subscribeToExecution } from "../subscriptions";

export function useExecutionEvents(tenantId: string, executionId: string) {
  const client = useMemo(() => getRealtimeClient(tenantId), [tenantId]);
  const [received, setReceived] = useState<{ client: RealtimeClient; resource: string; events: RealtimeEvent[] } | null>(null);
  useEffect(() => {
    let active = true;
    const sub = subscribeToExecution(client, executionId, (event) => {
      if (!active) return;
      setReceived((previous) => ({
        client, resource: executionId, events: [
          ...(previous?.client === client && previous.resource === executionId ? previous.events : []),
          event,
        ],
      }));
    });
    return () => {
      active = false;
      client.unsubscribe(sub.subscriptionId);
      client.disconnect();
    };
  }, [client, executionId]);

  // A render for a different principal/resource must not display old state,
  // even before effects clean up the old subscription.
  return { events: received?.client === client && received.resource === executionId ? received.events : [] };
}
