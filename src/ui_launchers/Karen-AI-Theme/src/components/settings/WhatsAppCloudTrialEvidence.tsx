'use client';

/** Read-only projection of canonical channel ledger facts for a real operator trial. */
import { useState } from 'react';
import { AlertCircle, Loader2, Search } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ApiError, apiClient } from '@/lib/api';

const INBOUND_ID = /^wamid\.[A-Za-z0-9._+=/-]{1,250}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DIGEST = /^[0-9a-f]{64}$/;
const INBOX_STATES = new Set(['pending', 'processing', 'completed', 'failed']);
const OUTBOX_STATES = new Set(['accepted', 'sent', 'delivered', 'read', 'failed', 'unknown']);
const RECEIPT_STATES = new Set(['sent', 'delivered', 'read', 'failed']);

type Trial = Readonly<{
  inbox_id: string;
  correlation_id: string;
  connection_revision: number;
  current_connection_revision: number;
  connection_enabled: boolean;
  inbox_status: 'pending' | 'processing' | 'completed' | 'failed';
  binding_currently_active: boolean;
  outbound_delivery_id: string | null;
  outbound_status: 'accepted' | 'sent' | 'delivered' | 'read' | 'failed' | 'unknown' | null;
  outbound_provider_message_sha256: string | null;
  provider_receipt_states: string[];
  evidence_basis: 'host_persisted_lineage_only';
  meta_origin_independently_verified: false;
  consumer_certified: false;
}>;

function parseTrial(value: unknown): Trial {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Unverified trial projection');
  }
  const r = value as Record<string, unknown>;
  const allowed = [
    'inbox_id', 'correlation_id', 'connection_revision', 'current_connection_revision',
    'connection_enabled', 'inbox_status', 'binding_currently_active',
    'outbound_delivery_id', 'outbound_status', 'outbound_provider_message_sha256',
    'provider_receipt_states', 'evidence_basis',
    'meta_origin_independently_verified', 'consumer_certified',
  ];
  if (
    Object.keys(r).length !== allowed.length ||
    Object.keys(r).some((key) => !allowed.includes(key)) ||
    typeof r.inbox_id !== 'string' || !UUID.test(r.inbox_id) ||
    typeof r.correlation_id !== 'string' || !UUID.test(r.correlation_id) ||
    typeof r.connection_revision !== 'number' ||
    !Number.isSafeInteger(r.connection_revision) || r.connection_revision < 1 ||
    typeof r.current_connection_revision !== 'number' ||
    !Number.isSafeInteger(r.current_connection_revision) ||
    r.current_connection_revision < 1 ||
    typeof r.connection_enabled !== 'boolean' ||
    typeof r.binding_currently_active !== 'boolean' ||
    typeof r.inbox_status !== 'string' || !INBOX_STATES.has(r.inbox_status) ||
    (r.outbound_delivery_id !== null &&
      (typeof r.outbound_delivery_id !== 'string' || !UUID.test(r.outbound_delivery_id))) ||
    (r.outbound_status !== null &&
      (typeof r.outbound_status !== 'string' || !OUTBOX_STATES.has(r.outbound_status))) ||
    (r.outbound_provider_message_sha256 !== null &&
      (typeof r.outbound_provider_message_sha256 !== 'string' ||
        !DIGEST.test(r.outbound_provider_message_sha256))) ||
    !Array.isArray(r.provider_receipt_states) ||
    r.provider_receipt_states.length > 4 ||
    r.provider_receipt_states.some((s: unknown) =>
      typeof s !== 'string' || !RECEIPT_STATES.has(s)) ||
    new Set(r.provider_receipt_states).size !== r.provider_receipt_states.length ||
    r.evidence_basis !== 'host_persisted_lineage_only' ||
    r.meta_origin_independently_verified !== false ||
    r.consumer_certified !== false ||
    (r.outbound_delivery_id === null && (r.outbound_status !== null ||
      r.outbound_provider_message_sha256 !== null ||
      r.provider_receipt_states.length !== 0)) ||
    (r.outbound_delivery_id !== null && r.inbox_status !== 'completed') ||
    (r.outbound_provider_message_sha256 === null && r.provider_receipt_states.length > 0)
  ) {
    throw new Error('Unverified trial projection');
  }
  return r as Trial;
}

function safeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Sign in to inspect the trial ledger.';
    if (error.status === 403) return 'Your account cannot inspect this connection.';
    if (error.status === 404) return 'No matching persisted trial evidence was found.';
    if (error.status === 422) return 'The supplied inbound message ID was rejected.';
    if (error.status === 503) return 'The trial evidence ledger is unavailable.';
  }
  return 'Karen could not verify the trial evidence. No provider claim is established.';
}

export default function WhatsAppCloudTrialEvidence({
  connectionId,
}: Readonly<{ connectionId: string }>) {
  const [eventId, setEventId] = useState('');
  const [evidence, setEvidence] = useState<Trial | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inspect = async () => {
    if (pending || !UUID.test(connectionId) || !INBOUND_ID.test(eventId)) return;
    setPending(true);
    setError(null);
    setEvidence(null);
    try {
      const response = await apiClient.post<unknown>(
        `/api/channels/operator/whatsapp/connections/${connectionId}/trial-evidence`,
        { external_event_id: eventId },
      );
      setEvidence(parseTrial(response));
    } catch (failure) {
      setError(safeError(failure));
    } finally {
      setPending(false);
    }
  };

  return (
    <section className="space-y-3 border-t border-border/60 pt-3"
      aria-label="WhatsApp trial evidence inspection">
      <p className="text-sm font-semibold">Inspect a real message trial</p>
      <p className="text-xs text-muted-foreground">
        Enter the inbound Meta message ID from your approved provider-side test.
        Karen reads only its own tenant-scoped inbox, ChatRuntime outbox and
        signed-status ledger. This does not independently authenticate Meta origin.
      </p>
      <div className="space-y-2">
        <Label htmlFor={`whatsapp-trial-${connectionId}`}>Inbound WhatsApp message ID</Label>
        <Input id={`whatsapp-trial-${connectionId}`}
          autoComplete="off" spellCheck={false} maxLength={256}
          placeholder="wamid."
          value={eventId}
          onChange={(event) => {
            setEventId(event.target.value);
            setEvidence(null);
            setError(null);
          }}
          disabled={pending}
        />
      </div>
      <Button type="button" size="sm" variant="outline"
        disabled={pending || !INBOUND_ID.test(eventId)}
        onClick={() => void inspect()}>
        {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> :
          <Search className="mr-2 h-4 w-4" aria-hidden="true" />}
        Inspect persisted evidence
      </Button>
      {error && (
        <Alert role="alert" variant="destructive">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Evidence unavailable</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {evidence && (
        <div className="space-y-2 rounded-md border p-3 text-xs" role="status">
          <p><strong>Inbox:</strong> {evidence.inbox_status}</p>
          <p><strong>Original connection revision:</strong> {evidence.connection_revision}</p>
          <p><strong>Current revision:</strong> {evidence.current_connection_revision}</p>
          <p><strong>Current binding:</strong> {evidence.binding_currently_active
            ? 'Recorded as active' : 'Not currently active'}</p>
          <p><strong>ChatRuntime outbox:</strong> {evidence.outbound_status ??
            'No durable reply staged'}</p>
          <p><strong>Provider send receipt ID:</strong> {evidence.outbound_provider_message_sha256
            ? 'Stored as a SHA-256 fingerprint' : 'Not recorded'}</p>
          <p><strong>Provider status observations:</strong> {evidence.provider_receipt_states.length
            ? evidence.provider_receipt_states.join(', ') : 'None recorded'}</p>
          <p className="break-all"><strong>Correlation ID:</strong> {evidence.correlation_id}</p>
          <p className="font-medium">
            Host-persisted history only. Independent Meta-origin verification and
            consumer certification are not established.
          </p>
        </div>
      )}
    </section>
  );
}
