import { useEffect, useMemo, useState } from "react";
import { RealtimeEvent } from "../types";
import { RealtimeClient } from "../client";
import { getRealtimeClient } from "./useRealtimeConnection";
import { subscribeToNotifications } from "../subscriptions";

export function useUserNotifications(tenantId: string) {
  const client = useMemo(() => getRealtimeClient(tenantId), [tenantId]);
  const [received, setReceived] = useState<{ client: RealtimeClient; events: RealtimeEvent[] } | null>(null);
  useEffect(() => {
    let active = true;
    const sub = subscribeToNotifications(client, (event) => {
      if (!active) return;
      setReceived((previous) => ({
        client, events: [
          ...(previous?.client === client ? previous.events : []),
          event,
        ],
      }));
    });
    return () => {
      active = false;
      client.unsubscribe(sub.subscriptionId);
      client.disconnect();
    };
  }, [client]);

  // A render for a different principal/resource must not display old state,
  // even before effects clean up the old subscription.
  return { notifications: received?.client === client ? received.events : [] };
}
