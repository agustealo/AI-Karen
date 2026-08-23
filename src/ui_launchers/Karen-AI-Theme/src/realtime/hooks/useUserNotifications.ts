import { useEffect, useRef, useState } from "react";
import { RealtimeEvent } from "../types";
import { getRealtimeClient } from "./useRealtimeConnection";
import { subscribeToNotifications } from "../subscriptions";

export function useUserNotifications(tenantId: string) {
  const [notifications, setNotifications] = useState<RealtimeEvent[]>([]);
  const clientRef = useRef(getRealtimeClient(tenantId));

  useEffect(() => {
    const client = clientRef.current;
    const sub = subscribeToNotifications(client, (event) => {
      setNotifications((prev) => [...prev, event]);
    });
    return () => client.unsubscribe(sub.subscriptionId);
  }, [tenantId]);

  return { notifications };
}
