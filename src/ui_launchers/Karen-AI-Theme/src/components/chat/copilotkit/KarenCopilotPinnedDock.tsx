"use client";

/**
 * KUI-002D3L: presentation controls remain default-off in the actual host.
 * Only fresh authenticated capability evidence can expose guarded actions
 * when a future release boundary explicitly opts into presentation controls.
 *
 * The backend independently authorizes each mutation and commits immutable
 * receipts. The dock performs no optimistic moves, POST retry, raw pointer
 * reconstruction, local authority caching, or cross-session persistence.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Bookmark, ShieldCheck, X } from "lucide-react";
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

const pinCapability = z.object({
  schema_version: z.literal(1),
  mutation_enabled: z.boolean(),
  allowed_operations: z.array(z.enum(["unpin", "reorder"])).max(2),
  denial_reason: z.union([z.literal("mutations_disabled"), z.null()]),
}).strict();

type MutationAction = "unpin" | "reorder";

export function parseAuthenticatedPinCapability(value: unknown): MutationAction[] {
  const result = pinCapability.safeParse(value);
  if (!result.success) return [];
  const { mutation_enabled, allowed_operations, denial_reason } = result.data;
  if (!mutation_enabled || denial_reason !== null ||
      new Set(allowed_operations).size !== allowed_operations.length) return [];
  return allowed_operations;
}

const committedReceipt = z.object({
  schema_version: z.literal(1),
  committed: z.literal(true),
  receipt: z.object({
    receipt_id: z.string().min(1),
    idempotency_key: z.string().uuid(),
    operation: z.enum(["unpin", "reorder"]),
    pin_id: z.string().uuid(),
  }).passthrough(),
}).passthrough();

type PinReference = z.infer<typeof pinReference>;
type DockState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "available"; pins: PinReference[] }
  | { kind: "unavailable" };

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
  const [allowedOps, setAllowedOps] = useState<MutationAction[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const mountedRef = useRef(false);
  const readGenerationRef = useRef(0);
  const mutatingRef = useRef(false);

  const refresh = useCallback(async () => {
    const generation = ++readGenerationRef.current;
    setState({ kind: "loading" });
    setAllowedOps([]);
    try {
      const [referenceResponse, capabilityResponse] = await Promise.all([
        apiClient.get<unknown>("/api/chat/ag-ui/pins"),
        mutationControlsEnabled
          ? apiClient.get<unknown>("/api/chat/ag-ui/pins/capabilities").catch(() => null)
          : Promise.resolve(null),
      ]);
      if (!mountedRef.current || generation !== readGenerationRef.current) return null;
      const pins = parseAuthorizedPinReadback(referenceResponse);
      setAllowedOps(mutationControlsEnabled && pins !== null
        ? parseAuthenticatedPinCapability(capabilityResponse) : []);
      setState(pins === null
        ? { kind: "unavailable" }
        : pins.length === 0 ? { kind: "empty" } : { kind: "available", pins });
      return pins;
    } catch {
      if (mountedRef.current && generation === readGenerationRef.current) {
        setAllowedOps([]);
        setState({ kind: "unavailable" });
      }
      return null;
    }
  }, [mutationControlsEnabled]);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();
    return () => {
      mountedRef.current = false;
      readGenerationRef.current += 1;
    };
  }, [refresh]);

  const mutate = useCallback(async (
    pin: PinReference, operation: MutationAction, destination?: number,
  ) => {
    if (!mutationControlsEnabled || !allowedOps.includes(operation) ||
        mutatingRef.current || state.kind !== "available" ||
        (operation === "reorder" && !state.pins.every((entry, i) => entry.position === i))) return;
    mutatingRef.current = true;
    setPending(true);
    setMessage(null);
    const generation = ++readGenerationRef.current;
    let verified = false;
    let conflict = false;
    let attempted = false;
    try {
      // A displayed control never grants execution; recheck the authenticated
      // capability immediately before every single-shot mutation POST.
      const freshOps = parseAuthenticatedPinCapability(
        await apiClient.get<unknown>("/api/chat/ag-ui/pins/capabilities"),
      );
      if (!mountedRef.current || generation !== readGenerationRef.current ||
          !freshOps.includes(operation)) {
        setAllowedOps([]);
        return;
      }
      const idempotencyKey = crypto.randomUUID();
      const request = operation === "reorder" ? {
        operation, idempotency_key: idempotencyKey, pin_id: pin.pin_id,
        expected_revision: pin.revision, position: destination,
      } : {
        operation, idempotency_key: idempotencyKey, pin_id: pin.pin_id,
      };
      attempted = true;
      const answer = await apiClient.post<unknown>(
        "/api/chat/ag-ui/pins/mutations", request,
      );
      verified = verifyCommittedPinMutation(answer, operation, pin.pin_id, idempotencyKey);
    } catch (error) {
      conflict = error instanceof ApiError && error.status === 409;
    } finally {
      // Never optimistically alter pin state, replay a POST, or trust a
      // receipt without fresh authorized readback.
      if (mountedRef.current) {
        const confirmedPins = await refresh();
        if (mountedRef.current && attempted) {
          // A committed receipt is necessary but not sufficient. The scoped
          // post-write read must reflect the requested removal or revisioned
          // move before the UI can consider the mutation confirmed.
          const readbackConfirmed = verified && confirmedPins !== null && (
            operation === "unpin"
              ? !confirmedPins.some(entry => entry.pin_id === pin.pin_id)
              : confirmedPins.some(entry =>
                  entry.pin_id === pin.pin_id &&
                  entry.position === destination &&
                  entry.revision > pin.revision)
          );
          if (verified && !readbackConfirmed) {
            // Fail closed on stale, contradictory or unavailable evidence;
            // never expose an apparently authoritative stale pin row.
            readGenerationRef.current += 1;
            setAllowedOps([]);
            setState({ kind: "unavailable" });
          }
          setMessage(readbackConfirmed
            ? null
            : conflict
              ? "Saved references changed elsewhere. Review the refreshed list."
              : verified
                ? "Pin change not confirmed by readback. Reload your workspace to verify."
                : "Pin change not confirmed. Review the refreshed list.");
        }
      }
      mutatingRef.current = false;
      if (mountedRef.current) setPending(false);
    }
  }, [allowedOps, mutationControlsEnabled, refresh, state]);

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
          Authorized saved references{mutationControlsEnabled && allowedOps.length ? "" : ", read only"}
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
                {mutationControlsEnabled && allowedOps.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1" data-testid="karen-pin-controls">
                    {allowedOps.includes("reorder") && state.pins.every((entry, i) => entry.position === i) && index > 0 && (
                      <button type="button" aria-label={`Move reference ${index + 1} up`}
                        disabled={pending} onClick={() => void mutate(pin, "reorder", index - 1)}
                        className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40">
                        <ArrowUp aria-hidden="true" className="mr-1 inline h-3 w-3" /> Move up
                      </button>
                    )}
                    {allowedOps.includes("reorder") && state.pins.every((entry, i) => entry.position === i) && index < state.pins.length - 1 && (
                      <button type="button" aria-label={`Move reference ${index + 1} down`}
                        disabled={pending} onClick={() => void mutate(pin, "reorder", index + 1)}
                        className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40">
                        <ArrowDown aria-hidden="true" className="mr-1 inline h-3 w-3" /> Move down
                      </button>
                    )}
                    {allowedOps.includes("unpin") && (
                      <button type="button" aria-label={`Unpin reference ${index + 1}`}
                        disabled={pending} onClick={() => void mutate(pin, "unpin")}
                        className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40">
                        <X aria-hidden="true" className="mr-1 inline h-3 w-3" /> Unpin
                      </button>
                    )}
                  </div>
                )}
              </article>
            ))}
            <p className="text-xs text-muted-foreground">
              References were reauthorized by Karen. Full cards cannot be restored
              from pointers alone. {mutationControlsEnabled && allowedOps.length
                ? "Changes require a committed server receipt and fresh readback."
                : "Pin changes are not available here."}
            </p>
          </section>
        )}
      </div>
    </aside>
  );
}
