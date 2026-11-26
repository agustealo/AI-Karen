/** Strict projection of the authenticated Communications inbox wire contract. */
export const INBOX_PATH = "/api/communications-center/inbox";
export const PAGE_SIZE = 25;
// UI read cadence, not a delivery SLA or transport connection status.
export const INBOX_REFRESH_INTERVAL_MS = 30_000;
export const INBOX_REFRESH_MIN_GAP_MS = 1_000;
export type InboxFilter = "active" | "archived" | "all";
export type InboxOperation = "read" | "acknowledge" | "archive";
export type InboxCursor = { created_at: string; entry_id: string };
export type InboxEntry = {
  entry_id: string;
  conversation_id: string;
  execution_id: string;
  source_kind: "terminal_chat_attention";
  source_status: "failed" | "orphaned";
  created_at: string;
  read_at: string | null;
  acknowledged_at: string | null;
  archived_at: string | null;
  revision: string;
};
export type InboxPage = {
  entries: InboxEntry[];
  next_cursor: InboxCursor | null;
  active_unread_count: number;
};
const MAX_REVISION = "9223372036854775806";
const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const isUuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const isTime = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(v) && Number.isFinite(Date.parse(v));
const nullableTime = (v: unknown): v is string | null => v === null || isTime(v);
const validRevision = (v: unknown): v is string => typeof v === "string" && /^[1-9][0-9]{0,18}$/.test(v)
  && (v.length < MAX_REVISION.length || v <= MAX_REVISION);
export const isEntry = (v: unknown): v is InboxEntry => {
  if (!isObject(v) || !isUuid(v.entry_id) || !isUuid(v.conversation_id) || !isUuid(v.execution_id)
      || v.source_kind !== "terminal_chat_attention" || (v.source_status !== "failed" && v.source_status !== "orphaned")
      || !isTime(v.created_at) || !nullableTime(v.read_at) || !nullableTime(v.acknowledged_at)
      || !nullableTime(v.archived_at) || !validRevision(v.revision)) return false;
  const created = Date.parse(v.created_at);
  return (v.read_at === null || Date.parse(v.read_at) >= created)
    && (v.archived_at === null || Date.parse(v.archived_at) >= created)
    && (v.acknowledged_at === null || (v.read_at !== null && Date.parse(v.acknowledged_at) >= Date.parse(v.read_at)));
};
export const isCursor = (v: unknown): v is InboxCursor => isObject(v) && isUuid(v.entry_id) && isTime(v.created_at);
export function readPage(v: unknown, filter: InboxFilter, previous: InboxCursor | null): InboxPage {
  if (!isObject(v) || !Array.isArray(v.entries) || v.entries.length > PAGE_SIZE
    || !v.entries.every(isEntry) || typeof v.active_unread_count !== "number"
    || !Number.isSafeInteger(v.active_unread_count) || v.active_unread_count < 0
    || !(v.next_cursor === null || isCursor(v.next_cursor))) throw new Error("Invalid inbox page");
  const entries: InboxEntry[] = v.entries;
  if (new Set(entries.map(e => e.entry_id)).size !== entries.length
    || entries.some(e => (filter === "active" && e.archived_at !== null) || (filter === "archived" && e.archived_at === null))
    || (previous !== null && entries.some(e => e.entry_id === previous.entry_id))
    || entries.filter(e => e.archived_at === null && e.read_at === null).length > v.active_unread_count) throw new Error("Invalid inbox projection");
  const last = entries[entries.length - 1];
  if (v.next_cursor && (entries.length !== PAGE_SIZE || !last || last.entry_id !== v.next_cursor.entry_id
    || last.created_at !== v.next_cursor.created_at)) throw new Error("Invalid inbox cursor");
  return { entries, next_cursor: v.next_cursor, active_unread_count: v.active_unread_count };
}
export function operationRecorded(entry: InboxEntry, operation: InboxOperation): boolean {
  return operation === "read" ? entry.read_at !== null : operation === "acknowledge" ? entry.acknowledged_at !== null : entry.archived_at !== null;
}
export function readReceipt(v: unknown, original: InboxEntry, operation: InboxOperation): { entry: InboxEntry; changed: boolean } {
  if (!isObject(v) || typeof v.changed !== "boolean" || !isEntry(v.entry)) throw new Error("Invalid inbox receipt");
  const entry = v.entry;
  const before = BigInt(original.revision), after = BigInt(entry.revision);
  if (entry.entry_id !== original.entry_id || entry.execution_id !== original.execution_id
    || entry.conversation_id !== original.conversation_id || entry.created_at !== original.created_at
    || entry.source_kind !== original.source_kind || !operationRecorded(entry, operation)
    || (original.read_at !== null && original.read_at !== entry.read_at)
    || (original.acknowledged_at !== null && original.acknowledged_at !== entry.acknowledged_at)
    || (original.archived_at !== null && original.archived_at !== entry.archived_at)
    || (v.changed ? after !== before + BigInt(1) : after <= before)) throw new Error("Unverified inbox mutation receipt");
  return { entry, changed: v.changed };
}
export function inboxPagePath(filter: InboxFilter, cursor: InboxCursor | null): string {
  const query = new URLSearchParams({ limit: String(PAGE_SIZE), inbox_filter: filter });
  if (cursor) { query.set("cursor_at", cursor.created_at); query.set("cursor_id", cursor.entry_id); }
  return INBOX_PATH + "?" + query.toString();
}
