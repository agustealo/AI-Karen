"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { useSession } from "@/components/chat/SessionProvider";

const HANDOFF_ERROR = "Unable to open that conversation. It may be unavailable or you may not have access.";

/**
 * Consumer workspace navigation only. SessionProvider owns conversation
 * loading and identity verification; a resolved false is NOT a successful
 * load. Never resume an approval or submit a message from this handoff.
 * Mount beneath the authenticated principal boundary.
 */
export function useVerifiedConversationHandoff(openChat: () => void) {
  const { loadSession } = useSession();
  const [handoffError, setHandoffError] = useState("");
  const live = useRef(false);
  const epoch = useRef(0);
  const pending = useRef(false);

  useLayoutEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      epoch.current += 1;
    };
  }, []);

  const openConversation = useCallback(async (conversationId: string) => {
    if (!live.current || pending.current) return;
    pending.current = true;
    const startedEpoch = epoch.current;
    const isCurrent = () => live.current && epoch.current === startedEpoch;
    setHandoffError("");

    try {
      const verified = await loadSession(conversationId);
      if (!isCurrent()) return;
      if (verified !== true) {
        setHandoffError(HANDOFF_ERROR);
        return;
      }
      openChat();
    } catch {
      if (isCurrent()) setHandoffError(HANDOFF_ERROR);
    } finally {
      pending.current = false;
    }
  }, [loadSession, openChat]);

  return { openConversation, handoffError };
}
