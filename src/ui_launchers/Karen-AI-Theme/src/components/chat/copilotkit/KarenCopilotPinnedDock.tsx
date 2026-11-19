"use client";

/**
 * KUI-002E2: read-only display of freshly admitted presentation references.
 *
 * The canonical backend owns identity, persistence, completed-run attestation,
 * reauthorization and mutation decisions. Readback returns references only,
 * NOT renderable card data. Never reconstruct or synthesize a presentation
 * from a pointer. No client pin store, mutation API, or local fallback.
 */
import { useEffect, useState } from "react";
import { Bookmark, ShieldCheck } from "lucide-react";
import { z } from "zod";
import { apiClient } from "@/lib/api";

const pinReference = z.object({
  pin_id: z.string().uuid(),
  position: z.number().int().min(0).max(99),
  revision: z.number().int().min(1).max(Number.MAX_SAFE_INTEGER),
  source: z.object({
    conversation_id: z.string().uuid(),
    assistant_message_id: z.string().uuid(),
    presentation_id: z.string().min(1).max(160),
    evidence_ref: z.string().min(1).max(160),
    component_type: z.string().min(1).max(100),
    schema_version: z.number().int().min(1),
  }).strict(),
}).strict();

const pinReadback = z.object({
  schema_version: z.literal(1),
  read_only: z.literal(true),
  pins: z.array(pinReference).max(100),
}).strict();

type PinReference = z.infer<typeof pinReference>;
type DockState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "available"; pins: PinReference[] }
  | { kind: "unavailable" };

/** Validate the entire snapshot before making any reference visible. */
export function parseAuthorizedPinReadback(value: unknown): PinReference[] | null {
  const parsed = pinReadback.safeParse(value);
  if (!parsed.success) return null;
  const pins = parsed.data.pins;
  const ids = new Set<string>();
  const positions = new Set<number>();
  for (const pin of pins) {
    if (ids.has(pin.pin_id) || positions.has(pin.position)) return null;
    ids.add(pin.pin_id);
    positions.add(pin.position);
  }
  return pins.slice().sort((left, right) => left.position - right.position);
}

export function KarenCopilotPinnedDock() {
  const [state, setState] = useState<DockState>({ kind: "loading" });

  useEffect(() => {
    // An obsolete response must not repaint a different user/conversation.
    // The authenticated CopilotKit provider is already keyed by principal.
    let mounted = true;
    void apiClient.get<unknown>("/api/chat/ag-ui/pins")
      .then((response) => {
        if (!mounted) return;
        const pins = parseAuthorizedPinReadback(response);
        if (pins === null) {
          setState({ kind: "unavailable" });
        } else if (pins.length === 0) {
          setState({ kind: "empty" });
        } else {
          setState({ kind: "available", pins });
        }
      })
      .catch(() => {
        if (mounted) setState({ kind: "unavailable" });
      });
    return () => { mounted = false; };
  }, []);

  return (
    <aside aria-label="Pinned workspace"
      data-testid="karen-copilot-pinned-dock"
      data-kari-region="dock"
      className="karen-pinned-dock">
      <header className="karen-pinned-dock-header">
        <div className="flex min-w-0 items-center gap-2">
          <Bookmark aria-hidden="true" className="h-4 w-4 shrink-0 text-primary" />
          <h2 className="truncate font-semibold">Pinned workspace</h2>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          Authorized saved references, read only
        </p>
      </header>
      <div className="karen-pinned-dock-scroll">
        {state.kind === "loading" && (
          <p role="status" data-testid="karen-pins-loading" className="p-4 text-xs text-muted-foreground">
            Checking your saved references…
          </p>
        )}
        {state.kind === "empty" && (
          <section aria-label="No saved references" data-testid="karen-pins-empty"
            className="rounded-xl border border-border/70 bg-card p-4">
            <p className="text-sm font-semibold">No authorized pinned references</p>
            <p className="mt-2 text-xs text-muted-foreground">
              Nothing is currently available from your verified saved pin records.
            </p>
          </section>
        )}
        {state.kind === "unavailable" && (
          <section aria-label="Pin readback unavailable" data-testid="karen-pinning-not-available"
            className="rounded-xl border border-border/70 bg-card p-4">
            <ShieldCheck aria-hidden="true" className="mb-3 h-5 w-5 text-primary" />
            <h3 className="text-sm font-semibold">Secure pinning not yet available</h3>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              Karen could not verify your saved pin references. No cards have
              been displayed or synced from this panel.
            </p>
          </section>
        )}
        {state.kind === "available" && (
          <section aria-label="Verified saved pin references" data-testid="karen-pins-authorized"
            className="space-y-2 p-3">
            {state.pins.map((pin) => (
              <article key={pin.pin_id} className="rounded-xl border border-border/70 bg-card p-3">
                <p className="break-words text-sm font-medium">
                  {pin.source.component_type.replace(/\./g, " · ")}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Saved reference {pin.position + 1} · Revision {pin.revision}
                </p>
              </article>
            ))}
            <p className="text-xs text-muted-foreground">
              References were reauthorized by Karen. Full cards cannot be restored
              from pointers alone. Pin changes are not available here.
            </p>
          </section>
        )}
      </div>
    </aside>
  );
}
