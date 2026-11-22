"use client";

/**
 * Response-aware presentation of canonical verified history.
 * Never infer evidence from transient SDK messages or user-controlled input.
 * Selection only changes which saved assistant turn is inspected.
 */
import { useEffect, useState } from "react";
import ConversationContextRail from "@/components/chat/ConversationContextRail";
import { KarenSafePresentation } from "@/components/chat/KarenSafePresentation";
import { useKarenVerifiedResponseContext } from "./KarenCopilotVerifiedHistory";

function ActivityReplayNotice() {
  return (
    <p role="status" data-testid="karen-copilot-activity-replay-unavailable"
      className="border-t border-border/60 px-3 py-2 text-xs text-muted-foreground">
      No attested agent steps are available for the selected saved assistant turn. No activity is inferred from SDK state.
    </p>
  );
}

function RailUnavailable({ embedded = false }: { embedded?: boolean }) {
  return (
    <aside aria-label="Conversation intelligence deck"
      data-testid="karen-copilot-rail-unverified"
      className={embedded
        ? "min-h-0 w-full p-3"
        : "hidden h-full min-h-0 w-[21rem] shrink-0 overflow-y-auto border-l border-border/70 bg-background/45 p-4 xl:block 2xl:w-[22rem]"}>
      <h2 className="text-sm font-semibold">Response context</h2>
      <p className="mt-3 text-sm text-muted-foreground">
        No backend-verified execution receipt is available for this response.
        Runtime details appear only after Karen confirms and saves execution.
      </p>
    </aside>
  );
}

export function KarenCopilotVerifiedRail() {
  const responses = useKarenVerifiedResponseContext();
  const latestId = responses.at(-1)?.messageId ?? null;
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Reject stale selected IDs after canonical history refresh or account switch.
  // A null selection means always follow the most recent assistant response.
  const selected = responses.find(item => item.messageId === selectedId)
    ?? responses.at(-1) ?? null;
  useEffect(() => {
    if (selectedId !== null && !responses.some(item => item.messageId === selectedId)) {
      setSelectedId(null);
    }
  }, [responses, selectedId]);

  const renderSwitcher = (controlId: string) => responses.length > 1 ? (
    <div data-testid="karen-response-context-picker"
      className="border-b border-border/60 px-3 py-3">
      <label htmlFor={controlId}
        className="mb-1 block text-xs font-semibold text-muted-foreground">
        Inspect saved response
      </label>
      <select id={controlId}
        value={selected?.messageId ?? ""}
        onChange={event => setSelectedId(
          event.target.value === latestId ? null : event.target.value,
        )}
        className="min-h-11 w-full max-w-full rounded-lg border border-input bg-background px-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-ring">
        {responses.map((item, index) => (
          <option key={item.messageId} value={item.messageId}>
            {index === responses.length - 1
              ? "Latest saved response"
              : `Saved response ${index + 1}`}
          </option>
        ))}
      </select>
      <p className="mt-1 text-xs text-muted-foreground">
        Verified history only. Selecting a response does not execute tools or change saved data.
      </p>
    </div>
  ) : null;

  const renderPresentations = () => selected && selected.presentations.length > 0 ? (
    <section aria-label="Response-linked verified cards"
      data-testid="karen-response-linked-presentations"
      className="space-y-3 border-b border-border/60 px-3 py-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Generated cards · {selected.presentations.length}
      </h3>
      {selected.presentations.map(presentation => (
        <article key={presentation.presentation_id}
          data-presentation-id={presentation.presentation_id}
          className="min-w-0 overflow-x-auto rounded-xl border border-border/70 bg-card p-2">
          <p className="mb-2 break-all font-mono text-[11px] text-muted-foreground">
            {presentation.component_type.replace(/\./g, " · ")}
          </p>
          <KarenSafePresentation data={presentation} />
        </article>
      ))}
      <p className="text-xs text-muted-foreground">
        These saved cards remain linked to their originating assistant response.
        Persistent pinning is unavailable until authorized storage is verified.
      </p>
    </section>
  ) : null;

  const context = selected?.receipt
    ? <><ConversationContextRail metadata={selected.receipt}
        agentSteps={selected.agentSteps} embedded />
        {selected.agentSteps.length === 0 && <ActivityReplayNotice />}</>
    : <RailUnavailable embedded />;

  return (
    <>
      <details data-testid="karen-copilot-mobile-intelligence"
        className="order-first w-full shrink-0 border-b border-border/70 bg-background/80 xl:hidden">
        <summary className="flex min-h-11 cursor-pointer items-center px-4 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-ring">
          Response context
        </summary>
        <div className="max-h-[min(55dvh,28rem)] min-h-0 overflow-y-auto overscroll-contain border-t border-border/60">
          {renderSwitcher("karen-verified-response-mobile")}
          {renderPresentations()}
          {context}
        </div>
      </details>
      <aside aria-label="Response context panel"
        data-testid="karen-copilot-response-context"
        className="hidden h-full min-h-0 w-[21rem] shrink-0 overflow-y-auto border-l border-border/70 bg-background/45 xl:block 2xl:w-[22rem]">
        <div className="border-b border-border/60 px-4 py-3">
          <h2 className="text-sm font-semibold">Response context</h2>
          <p className="text-xs text-muted-foreground">
            {selected ? "Evidence linked to the selected saved response" : "Awaiting verified saved history"}
          </p>
        </div>
        {renderSwitcher("karen-verified-response-desktop")}
        {renderPresentations()}
        {selected?.receipt
          ? <><ConversationContextRail metadata={selected.receipt}
              agentSteps={selected.agentSteps} embedded />
              {selected.agentSteps.length === 0 && <ActivityReplayNotice />}</>
          : <RailUnavailable embedded />}
      </aside>
    </>
  );
}
