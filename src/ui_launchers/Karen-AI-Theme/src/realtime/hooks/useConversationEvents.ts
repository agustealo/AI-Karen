import { useEffect, useMemo, useState } from "react";
import { RealtimeEvent } from "../types";
import { RealtimeClient } from "../client";
import { getRealtimeClient } from "./useRealtimeConnection";
import { subscribeToConversation } from "../subscriptions";

export function useConversationEvents(tenantId: string, conversationId: string) {
  const client = useMemo(() => getRealtimeClient(tenantId), [tenantId]);
  const [received, setReceived] = useState<{ client: RealtimeClient; resource: string; events: RealtimeEvent[] } | null>(null);
  useEffect(() => {
    let active = true;
    const sub = subscribeToConversation(client, conversationId, (event) => {
      if (!active) return;
      setReceived((previous) => ({
        client, resource: conversationId, events: [
          ...(previous?.client === client && previous.resource === conversationId ? previous.events : []),
          event,
        ],
      }));
    });
    return () => {
      active = false;
      client.unsubscribe(sub.subscriptionId);
      client.disconnect();
    };
  }, [client, conversationId]);

  // A render for a different principal/resource must not display old state,
  // even before effects clean up the old subscription.
  return { events: received?.client === client && received.resource === conversationId ? received.events : [] };
}
