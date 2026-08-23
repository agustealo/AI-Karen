import { useEffect, useRef, useState } from "react";
import { RealtimeEvent } from "../types";
import { getRealtimeClient } from "./useRealtimeConnection";
import { subscribeToConversation } from "../subscriptions";

export function useConversationEvents(tenantId: string, conversationId: string) {
  const [events, setEvents] = useState<RealtimeEvent[]>([]);
  const clientRef = useRef(getRealtimeClient(tenantId));

  useEffect(() => {
    const client = clientRef.current;
    const sub = subscribeToConversation(client, conversationId, (event) => {
      setEvents((prev) => [...prev, event]);
    });
    return () => client.unsubscribe(sub.subscriptionId);
  }, [tenantId, conversationId]);

  return { events };
}
