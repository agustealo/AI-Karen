"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { apiClient, captureApiPrincipalScope, isCurrentApiPrincipalScope, type ApiPrincipalScope } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  INBOX_PATH, inboxPagePath, operationRecorded, readPage, readReceipt,
  type InboxCursor, type InboxEntry, type InboxFilter, type InboxOperation, type InboxPage,
} from "./communications-inbox-contract";

type Props = {
  tenantId?: string;
  userId?: string;
  refreshRevision?: number;
  onOpenConversation?: (id: string) => Promise<void>;
};

export function PersonalCommunicationsInbox({ tenantId, userId, ...props }: Props) {
  const scope = tenantId && userId ? captureApiPrincipalScope(tenantId, userId) : null;
  if (!scope) return <p role="status">Sign in to view your personal inbox.</p>;
  return <ScopedInbox key={JSON.stringify(scope)} scope={scope} {...props} />;
}

function ScopedInbox({ scope: initialScope, refreshRevision, onOpenConversation }: Omit<Props, "tenantId" | "userId"> & { scope: ApiPrincipalScope }) {
  const [scope] = useState(initialScope);
  const [filter, setFilter] = useState<InboxFilter>("active");
  const [page, setPage] = useState<InboxPage | null>(null);
  const [cursor, setCursor] = useState<InboxCursor | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const live = useRef(false);
  const readEpoch = useRef(0);
  const writeLock = useRef(false);
  const handoffLock = useRef(false);
  const current = useCallback(() => live.current && isCurrentApiPrincipalScope(scope), [scope]);
  useLayoutEffect(() => {
    live.current = true;
    return () => { live.current = false; readEpoch.current += 1; };
  }, []);
  const load = useCallback(async (nextFilter: InboxFilter, nextCursor: InboxCursor | null, afterWrite = false) => {
    if (!current() || (writeLock.current && !afterWrite)) return;
    const epoch = ++readEpoch.current;
    setPage(null);
    setLoading(true);
    setError("");
    setFilter(nextFilter);
    setCursor(nextCursor);
    try {
      const raw = await apiClient.get<unknown>(inboxPagePath(nextFilter, nextCursor), scope);
      if (!current() || epoch !== readEpoch.current) return;
      setPage(readPage(raw, nextFilter, nextCursor));
      setUncertain(false);
    } catch {
      if (!current() || epoch !== readEpoch.current) return;
      setError("Personal inbox unavailable. Refresh to retrieve verified records.");
    } finally {
      if (current() && epoch === readEpoch.current) setLoading(false);
    }
  }, [current, scope]);
  useEffect(() => { void load("active", null); }, [load, refreshRevision]);

  async function perform(entry: InboxEntry, operation: InboxOperation) {
    if (!current() || writeLock.current || loading || uncertain || !page?.entries.includes(entry)
        || operationRecorded(entry, operation)) return;
    writeLock.current = true;
    readEpoch.current += 1;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const raw = await apiClient.patch<unknown>(INBOX_PATH + "/" + encodeURIComponent(entry.entry_id),
        { operation, expected_revision: entry.revision }, {}, scope);
      if (!current()) return;
      const receipt = readReceipt(raw, entry, operation);
      setNotice(receipt.changed ? "Notification state recorded." : "Notification state was already recorded.");
      await load(filter, null, true);
    } catch {
      if (!current()) return;
      setPage(null);
      setUncertain(true);
      setError("Notification change could not be verified. Refresh before trying again.");
    } finally {
      writeLock.current = false;
      if (current()) setBusy(false);
    }
  }

  async function reconcile() {
    if (!current() || writeLock.current || loading || uncertain || !page) return;
    writeLock.current = true;
    readEpoch.current += 1;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const raw = await apiClient.post<unknown>(INBOX_PATH + "/reconcile", undefined, {}, scope);
      if (!current()) return;
      const count = (raw as { admitted_count?: unknown } | null)?.admitted_count;
      if (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0 || count > 50) throw new Error("Invalid recovery receipt");
      setNotice(count === 0 ? "No additional entries were admitted in this recovery batch." : count + " additional entries admitted in this recovery batch.");
      await load(filter, null, true);
    } catch {
      if (!current()) return;
      setPage(null);
      setUncertain(true);
      setError("Notification recovery is unavailable or could not be verified. Refresh before trying again.");
    } finally {
      writeLock.current = false;
      if (current()) setBusy(false);
    }
  }
  async function openConversation(entry: InboxEntry) {
    if (!current() || writeLock.current || handoffLock.current || !onOpenConversation || !page?.entries.includes(entry)) return;
    handoffLock.current = true;
    try { await onOpenConversation(entry.conversation_id); }
    catch { if (current()) setError("Unable to open the verified conversation."); }
    finally { handoffLock.current = false; }
  }

  if (!isCurrentApiPrincipalScope(scope)) return <p role="status">Account changed. Reopen your inbox.</p>;
  const disabled = busy || loading || uncertain || !page;
  return <Card data-testid="personal-communications-inbox">
    <CardHeader>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Personal inbox</CardTitle>
          <CardDescription>Durable attention records from eligible failed or interrupted chat executions. Acknowledgment does not restart work or approve an action.</CardDescription>
        </div>
        <Badge variant="secondary" data-testid="personal-inbox-unread">{page === null ? "Unread unavailable" : page.active_unread_count + " unread active"}</Badge>
      </div>
    </CardHeader>
    <CardContent className="space-y-4">
      <div className="flex flex-wrap gap-2" aria-label="Inbox controls">
        {(["active", "archived", "all"] as const).map(value =>
          <Button key={value} type="button" size="sm" variant={filter === value ? "default" : "outline"} aria-pressed={filter === value}
            disabled={busy || loading || uncertain} onClick={() => { setNotice(""); void load(value, null); }}>{value === "active" ? "Active" : value === "archived" ? "Archived" : "All"}</Button>)}
        <Button type="button" size="sm" variant="outline" disabled={busy || loading} onClick={() => { setNotice(""); void load(filter, null); }}>Refresh inbox</Button>
        <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void reconcile()}>Recover missed notifications</Button>
      </div>
      {notice && <p role="status" className="text-sm text-muted-foreground">{notice}</p>}
      {error && <p role="alert" className="rounded-lg border p-3 text-sm text-destructive">{error}</p>}
      {loading && <p role="status" className="text-sm text-muted-foreground">Loading verified inbox…</p>}
      {page && page.entries.length === 0 && <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No records returned in this view. This is not proof that all executions succeeded or that the producer is enabled.</p>}
      {page && page.entries.length > 0 && <ol className="divide-y" aria-label="Verified personal notifications">
        {page.entries.map(entry => <li key={entry.entry_id} className="space-y-3 py-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-semibold">{entry.source_status === "failed" ? "Chat execution failed" : "Chat execution interrupted"}</p>
              <p className="text-xs text-muted-foreground">Execution {entry.execution_id.slice(0, 8)} · <time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</time></p>
            </div>
            <div className="flex flex-wrap gap-1">
              {entry.archived_at && <Badge variant="outline">Archived</Badge>}
              {entry.acknowledged_at ? <Badge variant="outline">Acknowledged</Badge> : <Badge variant="outline">{entry.read_at ? "Read" : "Unread"}</Badge>}
            </div>
          </div>
          <p className="text-sm text-muted-foreground">{entry.source_status === "orphaned" ? "The execution could not be confirmed as complete. Review the original conversation; this notification does not authorize a retry." : "Review the original conversation for context. No raw runtime errors are included here."}</p>
          <div className="flex flex-wrap gap-2">
            {onOpenConversation && <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => void openConversation(entry)}>Open original conversation</Button>}
            {(["read", "acknowledge", "archive"] as const).map(operation => <Button key={operation} type="button" size="sm" variant="outline"
              disabled={disabled || operationRecorded(entry, operation)} onClick={() => void perform(entry, operation)}>
              {operation === "read" ? "Mark read" : operation === "acknowledge" ? "Acknowledge" : "Archive"}
            </Button>)}
          </div>
        </li>)}
      </ol>}
      {page && (cursor || page.next_cursor) && <div className="flex flex-wrap gap-2">
        {cursor && <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void load(filter, null)}>First page</Button>}
        {page.next_cursor && <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void load(filter, page.next_cursor)}>Next page</Button>}
      </div>}
    </CardContent>
  </Card>;
}
