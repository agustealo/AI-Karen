import { useEffect, useRef, useState } from "react";
import { ConnectionState } from "../types";
import { RealtimeClient } from "../client";

let globalClient: RealtimeClient | null = null;

export function getRealtimeClient(tenantId: string): RealtimeClient {
  if (!globalClient || globalClient.connectionState === "disconnected") {
    globalClient = new RealtimeClient(tenantId);
  }
  return globalClient;
}

export function useRealtimeConnection(tenantId: string) {
  const [state, setState] = useState<ConnectionState>("disconnected");
  const clientRef = useRef<RealtimeClient | null>(null);

  if (!clientRef.current || clientRef.current.connectionState === "disconnected") {
    clientRef.current = getRealtimeClient(tenantId);
  }

  useEffect(() => {
    const client = clientRef.current!;
    setState(client.connectionState);
    const unsub = client.onStateChange((prev, next) => {
      setState(next);
    });
    client.connect();
    return () => {
      unsub();
      client.disconnect();
    };
  }, [tenantId]);

  return { state, client: clientRef.current };
}
