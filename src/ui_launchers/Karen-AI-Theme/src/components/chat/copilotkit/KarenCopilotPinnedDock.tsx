"use client";

/**
 * KUI-002D3H: read-only by default. Optional guarded unpin operates only
 * on backend-admitted saved references. Mutation eligibility is NOT inferred
 * from a client flag or an accessible transport endpoint. The existing host
 * deliberately passes no eligibility until an authenticated runtime
 * capability contract is available.
 *
 * Every mutation requires a matching committed backend receipt and then a
 * fresh authorized readback. No local pin cache, optimistic update, receipt
 * fabrication, card reconstruction, or POST retry. Reorder is withheld until\n * its backend contract guarantees an atomic collision-free move.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Bookmark, ShieldCheck, X } from "lucide-react";
import { z } from "zod";
import { apiClient, ApiError } from "@/lib/api";

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

const committedReceipt = z.object({
  schema_version: z.literal(1),
  committed: z.literal(true),
  receipt: z.object({
    receipt_id: z.string().min(1),
    idempotency_key: z.string().uuid(),
    operation: z.literal("unpin"),
    pin_id: z.string().uuid(),
  }).passthrough(),
}).passthrough();

type PinReference = z.infer<typeof pinReference>;
type DockState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "available"; pins: PinReference[] }
  | { kind: "unavailable" };
type MutationAction = "unpin";

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

export function verifyCommittedPinMutation(
  value: unknown,
  operation: MutationAction,
  pinId: string,
  idempotencyKey: string,
): boolean {
  const receipt = committedReceipt.safeParse(value);
  return receipt.success &&
    receipt.data.receipt.operation === operation &&
    receipt.data.receipt.pin_id === pinId &&
    receipt.data.receipt.idempotency_key === idempotencyKey;
}

interface KarenCopilotPinnedDockProps {
  /**
   * Must originate from future authenticated backend capability evidence.
   * This is a presentation gate, never permission; runtime checks every POST.
   * The consumer host intentionally does not supply the opt-in.
   */
  mutationControlsEnabled?: boolean;
}

export function KarenCopilotPinnedDock({
  mutationControlsEnabled = false,
}: KarenCopilotPinnedDockProps) {
  const [state, setState] = useState<DockState>({ kind: "loading" });
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const mountedRef = useRef(false);
  const readGenerationRef = useRef(0);
  const mutatingRef = useRef(false);

  const refresh = useCallback(async () => {
    const generation = ++readGenerationRef.current;
    setState({ kind: "loading" });
    try {
      const response = await apiClient.get<unknown>("/api/chat/ag-ui/pins");
      if (!mountedRef.current || generation !== readGenerationRef.current) return;
      const pins = parseAuthorizedPinReadback(response);
      setState(pins === null
        ? { kind: "unavailable" }
        : pins.length === 0 ? { kind: "empty" } : { kind: "available", pins });
    } catch {
      if (mountedRef.current && generation === readGenerationRef.current) {
        setState({ kind: "unavailable" });
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();
    return () => {
      mountedRef.current = false;
      readGenerationRef.current += 1;
    };
  }, [refresh]);

  const mutate = useCallback(async (pin: PinReference) => {
    if (!mutationControlsEnabled || mutatingRef.current || state.kind !== "available") return;
    // No mutation can derive authority from the displayed reference alone.
    // The authenticated runtime rechecks principal, revision and source.
    mutatingRef.current = true;
    setPending(true);
    setMessage(null);
    const idempotencyKey = crypto.randomUUID();
    const request = {
      operation: "unpin" as const,
      idempotency_key: idempotencyKey,
      pin_id: pin.pin_id,
    };
    let verified = false;
    let conflict = false;
    try {
      const answer = await apiClient.post<unknown>(
        "/api/chat/ag-ui/pins/mutations", request,
      );
      verified = verifyCommittedPinMutation(answer, "unpin", pin.pin_id, idempotencyKey);
    } catch (error) {
      conflict = error instanceof ApiError && error.status === 409;
    } finally {
      // A transport failure is ambiguous. Re-read backend truth, but NEVER
      // repeat the POST, move a row locally, or claim mutation success.
      if (mountedRef.current) {
        await refresh();
        if (mountedRef.current) {
          setMessage(verified
            ? null
            : conflict
              ? "Saved references changed elsewhere. Review the refreshed list."
              : "Pin change not confirmed. Review the refreshed list.");
        }
      }
      mutatingRef.current = false;
      if (mountedRef.current) setPending(false);
    }
  }, [mutationControlsEnabled, refresh, state]);

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
          Authorized saved references{mutationControlsEnabled ? "" : ", read only"}
        </p>
      </header>
      {message && <p role="status" data-testid="karen-pins-mutation-notice"
        className="px-3 py-2 text-xs text-muted-foreground">{message}</p>}
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
            {state.pins.map((pin, index) => (
              <article key={pin.pin_id} className="rounded-xl border border-border/70 bg-card p-3">
                <p className="break-words text-sm font-medium">
                  {pin.source.component_type.replace(/\./g, " · ")}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Saved reference {pin.position + 1} · Revision {pin.revision}
                </p>
                {mutationControlsEnabled && (
                  <div className="mt-2 flex flex-wrap gap-1" data-testid="karen-pin-controls">
                    <button type="button" aria-label={`Unpin reference ${index + 1}`}
                      disabled={pending}
                      onClick={() => void mutate(pin)}
                      className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40">
                      <X aria-hidden="true" className="mr-1 inline h-3 w-3" /> Unpin
                    </button>
                  </div>
                )}
              </article>
            ))}
            <p className="text-xs text-muted-foreground">
              References were reauthorized by Karen. Full cards cannot be restored
              from pointers alone. {mutationControlsEnabled
                ? "Changes require a committed server receipt and fresh readback."
                : "Pin changes are not available here."}
            </p>
          </section>
        )}
      </div>
    </aside>
  );
}
