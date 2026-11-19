import { AlertCircle, Inbox, LoaderCircle, LockKeyhole } from "lucide-react";

type AutomationNoticeKind = "loading" | "empty" | "unavailable" | "authentication";

interface AutomationListNoticeProps {
  kind: AutomationNoticeKind;
  message: string;
}

/**
 * Accessible, presentation-only list notice.
 *
 * The owning page decides whether authenticated data is ready, empty, denied,
 * or unavailable. Never infer successful reads from an empty array.
 */
export function AutomationListNotice({ kind, message }: AutomationListNoticeProps) {
  const Icon = kind === "loading"
    ? LoaderCircle
    : kind === "empty"
      ? Inbox
      : kind === "authentication"
        ? LockKeyhole
        : AlertCircle;
  const isError = kind === "unavailable";
  return (
    <div
      role={isError ? "alert" : "status"}
      aria-live={isError ? "assertive" : "polite"}
      className={`karen-automation-card flex min-w-0 items-start gap-3 rounded-xl border p-5 text-sm sm:p-6 ${
        isError ? "border-destructive/40 bg-destructive/5 text-foreground" : "border-border/70 bg-muted/20 text-muted-foreground"
      }`}
    >
      <Icon
        className={`mt-0.5 h-4 w-4 shrink-0 ${kind === "loading" ? "animate-spin" : ""}`}
        aria-hidden="true"
      />
      <p className="min-w-0 break-words">{message}</p>
    </div>
  );
}
