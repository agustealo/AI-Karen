import { useEffect, useRef, useState } from "react";
import { RealtimeEvent } from "../types";
import { getRealtimeClient } from "./useRealtimeConnection";
import { subscribeToExecution } from "../subscriptions";

export function useExecutionEvents(tenantId: string, executionId: string) {
  const [events, setEvents] = useState<RealtimeEvent[]>([]);
  const clientRef = useRef(getRealtimeClient(tenantId));

  useEffect(() => {
    const client = clientRef.current;
    const sub = subscribeToExecution(client, executionId, (event) => {
      setEvents((prev) => [...prev, event]);
    });
    return () => client.unsubscribe(sub.subscriptionId);
  }, [tenantId, executionId]);

  return { events };
}
