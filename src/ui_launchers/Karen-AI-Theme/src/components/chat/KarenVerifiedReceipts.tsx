"use client";

/** Canonical read-only execution and integrity receipt renderers, shared by chat surfaces. */
export function KarenResponseIntegrity({ data }: { data: unknown }) {
  if (!data || typeof data !== "object") return null;
  const receipt = data as Record<string, unknown>;
  const truncated = receipt.output_truncated === true;
  const recall = receipt.cortex_intent === "memory.recall" &&
    typeof receipt.personal_recall_grounded === "boolean";
  if (!truncated && !recall) return null;
  return (
    <section data-testid="karen-response-integrity" role="status" aria-live="polite"
      className="my-2 rounded-xl border border-border/60 px-3 py-2 text-xs">
      {truncated && <p data-testid="karen-output-truncated">
        This answer stopped at the model&apos;s output-token limit. It may be incomplete.
      </p>}
      {recall && <p data-testid="karen-recall-provenance">
        {receipt.personal_recall_grounded === true
          ? "Personal recall grounded in authorized evidence."
          : "Personal recall was not verified against authorized evidence."}
      </p>}
    </section>
  );
}

export function KarenRestoredExecutionReceipt({ data }: { data: unknown }) {
  if (!data || typeof data !== "object") return null;
  const receipt = data as Record<string, unknown>;
  if (
    typeof receipt.actual_provider !== "string" || !receipt.actual_provider ||
    typeof receipt.actual_model !== "string" || !receipt.actual_model ||
    typeof receipt.response_source !== "string" || !receipt.response_source
  ) return null;
  return (
    <details data-testid="karen-restored-execution-receipt"
      className="my-2 rounded-lg border border-border/60 px-3 py-2 text-xs">
      <summary className="cursor-pointer font-medium">Saved execution details</summary>
      {(typeof receipt.requested_provider === "string" || typeof receipt.requested_model === "string") && (
        <p className="mt-2">Requested: {String(receipt.requested_provider || "Unspecified")} · {String(receipt.requested_model || "Unspecified")}</p>
      )}
      <p className="mt-2">Executed provider: {receipt.actual_provider}</p>
      <p>Model: {receipt.actual_model}</p>
      <p>Response source: {receipt.response_source}</p>
      {typeof receipt.runtime_engine === "string" && receipt.runtime_engine &&
        <p>Engine: {receipt.runtime_engine}</p>}
      {typeof receipt.fallback_level === "number" && receipt.fallback_level > 0 &&
        <p>Fallback level: {receipt.fallback_level}</p>}
      {typeof receipt.degradation_reason === "string" && receipt.degradation_reason &&
        <p>Degradation reason: {receipt.degradation_reason.replace(/_/g, " ")}</p>}
      {receipt.degraded_mode === true && <p>Degraded execution reported</p>}
    </details>
  );
}

