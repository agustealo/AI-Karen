'use client';

/**
 * KOC-05: read-only, backend-owned personal channel inventory.
 *
 * Only the canonical ChannelHost may report an assigned connection or its
 * evidence status. This panel never initiates pairing, infers provider health,
 * manufactures a QR, or treats the last stored event as a live session.
 */

import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Loader2, RefreshCw, ShieldAlert } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { apiClient, ApiError } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';

type PersonalChannel = {
  connection_id: string;
  installation_id: string;
  provider_id: string | null;
  active_consent_provider_ids: string[];
  availability: 'configured' | 'unavailable';
  last_observed_phase: string | null;
  live_connected: boolean;
  qr_available: boolean;
  provider_unlinked: boolean;
};

type ChannelInventoryResponse = {
  connections: PersonalChannel[];
};

function isPersonalChannel(value: unknown): value is PersonalChannel {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.connection_id === 'string' &&
    typeof record.installation_id === 'string' &&
    (record.provider_id === null || typeof record.provider_id === 'string') &&
    Array.isArray(record.active_consent_provider_ids) &&
    record.active_consent_provider_ids.length <= 16 &&
    record.active_consent_provider_ids.every(
      (provider): provider is string =>
        typeof provider === 'string' &&
        provider.trim().length > 0 &&
        provider.length <= 128,
    ) &&
    new Set(record.active_consent_provider_ids).size === record.active_consent_provider_ids.length &&
    (record.availability === 'configured' || record.availability === 'unavailable') &&
    (record.last_observed_phase === null || typeof record.last_observed_phase === 'string') &&
    typeof record.live_connected === 'boolean' &&
    typeof record.qr_available === 'boolean' &&
    typeof record.provider_unlinked === 'boolean'
  );
}

function parseInventory(value: unknown): PersonalChannel[] {
  if (!value || typeof value !== 'object') {
    throw new Error('Channel inventory was not returned by Karen.');
  }
  const response = value as Partial<ChannelInventoryResponse>;
  if (!Array.isArray(response.connections) || !response.connections.every(isPersonalChannel)) {
    throw new Error('Channel inventory response is incomplete.');
  }
  return response.connections;
}

function readableFailure(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return 'Sign in to view your assigned channel connections.';
      case 403:
        return 'Karen did not authorize access to your channel connections.';
      case 503:
        return 'The Channels service is unavailable. No connection status has been verified.';
      default:
        return 'Karen could not verify your channel connections.';
    }
  }
  return 'Karen could not verify your channel connections.';
}


type ConsentStatus = {
  acknowledged: boolean;
  has_active_consent: boolean;
  policy_version: string;
  notice_title: string;
  notice_text: string;
  paired: boolean;
  provider_unlinked: boolean;
};

type ConsentReceipt = {
  acknowledged?: boolean;
  revoked?: boolean;
  paired?: boolean;
  provider_unlinked?: boolean;
};

function verifyConsentStatus(value: unknown): ConsentStatus {
  if (!value || typeof value !== 'object') {
    throw new Error('Invalid consent response');
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.acknowledged !== 'boolean' ||
    typeof record.has_active_consent !== 'boolean' ||
    (record.acknowledged && !record.has_active_consent) ||
    typeof record.policy_version !== 'string' ||
    !record.policy_version.trim() ||
    record.policy_version.length > 128 ||
    typeof record.notice_title !== 'string' ||
    !record.notice_title.trim() ||
    typeof record.notice_text !== 'string' ||
    !record.notice_text.trim() ||
    typeof record.paired !== 'boolean' ||
    typeof record.provider_unlinked !== 'boolean'
  ) {
    throw new Error('Incomplete consent response');
  }
  return record as ConsentStatus;
}

function PersonalChannelRiskConsent({
  connectionId,
  providerId,
  allowAcknowledgement,
}: {
  connectionId: string;
  providerId: string;
  allowAcknowledgement: boolean;
}) {
  const [status, setStatus] = useState<ConsentStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  const endpoint = '/api/channels/personal/' +
    encodeURIComponent(connectionId) + '/' + encodeURIComponent(providerId);
  const consentPath = endpoint + '/consent';
  const readConsent = useCallback(async () => verifyConsentStatus(
    await apiClient.get<ConsentStatus>(consentPath),
  ), [consentPath]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setStatus(null);
    setChecked(false);
    setError(null);
    setConfirmation(null);

    void readConsent()
      .then((result) => {
        if (!cancelled) {
          setStatus(result);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError('Current consent could not be verified. No change was made.');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [readConsent]);

  const refreshConsent = async () => {
    if (busy || loading) return;
    setLoading(true);
    setStatus(null);
    setChecked(false);
    setError(null);
    setConfirmation(null);
    try {
      setStatus(await readConsent());
    } catch {
      setError('Current consent could not be verified. No change was made.');
    } finally {
      setLoading(false);
    }
  };

  const mutateConsent = async (action: 'accept' | 'revoke') => {
    if (
      loading || busy || !status ||
      (action === 'accept' && (!allowAcknowledgement || status.has_active_consent || !checked)) ||
      (action === 'revoke' && !status.has_active_consent)
    ) return;

    const expectedVersion = status.policy_version;
    setBusy(true);
    setStatus(null);
    setChecked(false);
    setConfirmation(null);
    setError(null);

    try {
      const response = action === 'accept'
        ? await apiClient.post<ConsentReceipt>(consentPath, {
            accepted: true, policy_version: expectedVersion,
          })
        : await apiClient.post<ConsentReceipt>(endpoint + '/revoke', {});

      if (
        !response ||
        (action === 'accept' ? response.acknowledged !== true : response.revoked !== true) ||
        response.paired !== false ||
        response.provider_unlinked !== false
      ) {
        throw new Error('Consent mutation receipt unverified');
      }

      // A mutation receipt alone is not persisted truth. Always re-read.
      const fresh = await readConsent();
      if (
        fresh.has_active_consent !== (action === 'accept') ||
        fresh.acknowledged !== (action === 'accept') ||
        (action === 'accept' && fresh.policy_version !== expectedVersion)
      ) {
        throw new Error('Persisted consent did not confirm mutation');
      }
      setStatus(fresh);
      setConfirmation(action === 'accept'
        ? 'Risk acknowledgement verified in Karen. No WhatsApp device has been linked.'
        : 'Risk acknowledgement revoked in Karen. Remote unlink and credential erasure are not verified.');
    } catch {
      // The server may have committed before an ambiguous receipt was lost.
      // Never silently retry a mutation or claim it was rolled back.
      setStatus(null);
      setError('Consent change unverified. Refresh status before trying again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-3 border-t border-border/50 pt-4" aria-label="Personal connection risk consent">
      <p className="text-sm font-semibold">Unofficial personal WhatsApp risk consent</p>
      <p className="text-xs text-muted-foreground">
        This is not an account connection control. Consent does not create a QR,
        start a session, verify unlink, or erase provider credentials.
      </p>
      {loading && <p role="status">Checking stored risk acknowledgement...</p>}
      {!loading && status && (
        <>
          <p role="status" className="text-sm">
            <strong>Stored consent:</strong>{' '}
            {status.acknowledged
              ? 'Acknowledged'
              : status.has_active_consent
                ? 'Previous-policy acknowledgement still active'
                : 'Not acknowledged'}
          </p>
          {!allowAcknowledgement && (
            <p className="text-xs text-muted-foreground">
              This managed provider is no longer configured. Only revocation
              of existing consent is available; pairing and acknowledgement
              are disabled.
            </p>
          )}
          <div className="space-y-2 rounded-lg border border-border/60 bg-muted/20 p-3">
            <p className="font-semibold text-sm">{status.notice_title}</p>
            <p className="text-sm whitespace-pre-wrap">{status.notice_text}</p>
            <p className="text-xs text-muted-foreground">
              Current policy version: {status.policy_version}
            </p>
          </div>
          {allowAcknowledgement && !status.has_active_consent && (
            <>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(event) => setChecked(event.target.checked)}
                  aria-label="I explicitly accept the personal WhatsApp risks"
                />
                <span>I understand and explicitly accept these risks for this connection.</span>
              </label>
              <Button
                type="button"
                size="sm"
                disabled={!checked || busy}
                onClick={() => void mutateConsent('accept')}
              >
                Acknowledge risks
              </Button>
            </>
          )}
          {status.has_active_consent && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => void mutateConsent('revoke')}
              aria-label="Revoke personal WhatsApp risk consent"
            >
              Revoke consent
            </Button>
          )}
        </>
      )}
      {busy && <p role="status">Verifying the persisted consent change...</p>}
      {!busy && !loading && confirmation && (
        <p role="status" className="text-sm">{confirmation}</p>
      )}
      {!busy && !loading && error && (
        <Alert role="alert" variant="destructive">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Consent status unverified</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {!busy && !loading && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => void refreshConsent()}
          aria-label="Refresh personal channel consent"
        >
          Refresh consent status
        </Button>
      )}
    </section>
  );
}


type RetiredConsentRecord = {
  connection_id: string;
  provider_id: string;
  policy_version: string;
};

function parseRetiredConsentRecords(value: unknown): RetiredConsentRecord[] {
  if (!value || typeof value !== 'object') {
    throw new Error('Missing consent recovery records');
  }
  const records = (value as { consents?: unknown }).consents;
  if (!Array.isArray(records) || records.length > 50) {
    throw new Error('Unverified consent recovery inventory');
  }
  const seen = new Set<string>();
  for (const record of records) {
    if (!record || typeof record !== 'object') {
      throw new Error('Incomplete consent recovery record');
    }
    const item = record as Record<string, unknown>;
    if (
      typeof item.connection_id !== 'string' ||
      !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(item.connection_id) ||
      typeof item.provider_id !== 'string' ||
      !item.provider_id.trim() ||
      item.provider_id.length > 128 ||
      typeof item.policy_version !== 'string' ||
      !item.policy_version.trim() ||
      item.policy_version.length > 128
    ) {
      throw new Error('Invalid consent recovery record');
    }
    const key = item.connection_id + ':' + item.provider_id;
    if (seen.has(key)) {
      throw new Error('Duplicate consent recovery record');
    }
    seen.add(key);
  }
  return records as RetiredConsentRecord[];
}

function RetiredPersonalConsentRecovery({
  channels,
  authenticated,
}: {
  channels: PersonalChannel[] | null;
  authenticated: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [records, setRecords] = useState<RetiredConsentRecord[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  const endpoint = '/api/channels/personal/consent-recovery';
  const readRecords = async () => parseRetiredConsentRecords(
    await apiClient.get<{ consents: RetiredConsentRecord[] }>(endpoint),
  );

  const refreshRecords = async () => {
    if (!authenticated || loading || mutating) return;
    setExpanded(true);
    setLoading(true);
    setRecords(null);
    setFailure(null);
    setConfirmation(null);
    try {
      setRecords(await readRecords());
    } catch {
      setFailure('Stored channel consent could not be verified. No change was made.');
    } finally {
      setLoading(false);
    }
  };

  const revokeRecord = async (record: RetiredConsentRecord) => {
    if (!authenticated || loading || mutating || !records ||
        !records.some((item) =>
          item.connection_id === record.connection_id &&
          item.provider_id === record.provider_id,
        )) return;

    setMutating(true);
    setRecords(null);
    setFailure(null);
    setConfirmation(null);
    try {
      const path = endpoint + '/' + encodeURIComponent(record.connection_id) +
        '/' + encodeURIComponent(record.provider_id) + '/revoke';
      const receipt = await apiClient.post<ConsentReceipt>(path, {});
      if (!receipt || receipt.revoked !== true ||
          receipt.paired !== false || receipt.provider_unlinked !== false) {
        throw new Error('Retired consent revocation receipt is not authoritative');
      }
      const fresh = await readRecords();
      if (fresh.some((item) =>
        item.connection_id === record.connection_id &&
        item.provider_id === record.provider_id,
      )) {
        throw new Error('Durable consent revocation was not confirmed');
      }
      setRecords(fresh);
      setConfirmation(
        'Stored consent revocation verified. This does not unlink the provider or erase its data.',
      );
    } catch {
      // An ambiguous response may have committed. Never retry automatically.
      setRecords(null);
      setFailure('Revocation outcome unverified. Review the stored ledger again before retrying.');
    } finally {
      setMutating(false);
    }
  };

  const unrepresented = records?.filter((record) => !channels?.some(
    (channel) => channel.connection_id === record.connection_id &&
      channel.active_consent_provider_ids.includes(record.provider_id),
  ));

  return (
    <section className="space-y-3 border-t border-border/60 pt-4"
      aria-label="Retired channel consent recovery">
      <div className="space-y-2">
        <p className="text-sm font-semibold">Stored consent recovery</p>
        <p className="text-xs text-muted-foreground">
          Withdraw consent still recorded in Karen when a channel installation
          or its host is no longer running. This cannot reconnect or unlink a
          WhatsApp device, and is not proof of provider-side data deletion.
        </p>
        <Button type="button" variant="outline" size="sm"
          disabled={!authenticated || loading || mutating}
          onClick={() => void refreshRecords()}
          aria-label="Review stored channel consent">
          {expanded ? 'Refresh stored consent' : 'Review stored consent'}
        </Button>
      </div>
      {loading && <p role="status" className="text-sm">Reading the owned consent ledger...</p>}
      {mutating && <p role="status" className="text-sm">Verifying the consent withdrawal...</p>}
      {!loading && !mutating && failure && (
        <Alert role="alert" variant="destructive">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Stored consent unverified</AlertTitle>
          <AlertDescription>{failure}</AlertDescription>
        </Alert>
      )}
      {!loading && !mutating && confirmation && (
        <p role="status" className="text-sm">{confirmation}</p>
      )}
      {!loading && !mutating && unrepresented?.length === 0 && expanded && (
        <p role="status" className="text-xs text-muted-foreground">
          No separate active stored consent requires recovery. Any current
          channel consent is managed in its own connection card.
        </p>
      )}
      {!loading && !mutating && unrepresented && unrepresented.length > 0 && (
        <div className="space-y-3">
          {unrepresented.map((record) => (
            <div key={record.connection_id + ':' + record.provider_id}
              className="space-y-2 rounded-md border border-border/60 p-3">
              <p className="text-sm font-semibold">{record.provider_id}</p>
              <p className="break-all text-xs text-muted-foreground">
                Connection {record.connection_id}
              </p>
              <p className="text-xs text-muted-foreground">
                Recorded policy: {record.policy_version}. This acknowledgement
                does not establish a live or authorized provider session.
              </p>
              <Button type="button" variant="outline" size="sm"
                disabled={!authenticated || mutating || loading}
                onClick={() => void revokeRecord(record)}
                aria-label={'Revoke stored consent for ' + record.provider_id}>
                Revoke stored consent
              </Button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

type RetiredCredentialDeletion = {
  request_id: string;
  connection_id: string;
  provider_id: string;
  connection_revision: number;
  status:
    | 'requested'
    | 'provider_pending'
    | 'provider_claimed'
    | 'verification_pending'
    | 'verified'
    | 'unknown';
};

function parseRetiredCredentialDeletions(value: unknown): RetiredCredentialDeletion[] {
  if (!value || typeof value !== 'object') {
    throw new Error('Missing deletion request ledger');
  }
  const requests = (value as { requests?: unknown }).requests;
  if (!Array.isArray(requests) || requests.length > 50) {
    throw new Error('Invalid deletion request ledger');
  }
  const statuses = new Set([
    'requested', 'provider_pending', 'provider_claimed',
    'verification_pending', 'verified', 'unknown',
  ]);
  const seen = new Set<string>();
  for (const item of requests) {
    if (!item || typeof item !== 'object') {
      throw new Error('Invalid deletion request record');
    }
    const record = item as Record<string, unknown>;
    if (
      typeof record.request_id !== 'string' ||
      !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(record.request_id) ||
      typeof record.connection_id !== 'string' ||
      !record.connection_id.trim() || record.connection_id.length > 256 ||
      typeof record.provider_id !== 'string' ||
      !record.provider_id.trim() || record.provider_id.length > 128 ||
      typeof record.connection_revision !== 'number' ||
      !Number.isSafeInteger(record.connection_revision) || record.connection_revision < 1 ||
      typeof record.status !== 'string' || !statuses.has(record.status) ||
      seen.has(record.request_id)
    ) {
      throw new Error('Untrusted deletion request record');
    }
    seen.add(record.request_id);
  }
  return requests as RetiredCredentialDeletion[];
}

const deletionStatusDescription: Record<RetiredCredentialDeletion['status'], string> = {
  requested: 'Deletion requested in Karen. Provider outcome has not been verified.',
  provider_pending: 'Deletion request pending with the provider. Erasure has not been verified.',
  provider_claimed: 'Provider claims credential erasure. Independent verification is not established.',
  verification_pending: 'A verification step is pending. Erasure has not been confirmed here.',
  verified: 'Historical ledger status: verified. This screen does not independently verify provider or retained-data deletion.',
  unknown: 'Deletion outcome is unknown. No erasure confirmation is available.',
};

function RetiredCredentialDeletionHistory({ authenticated }: { authenticated: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const [records, setRecords] = useState<RetiredCredentialDeletion[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState(false);

  useEffect(() => {
    if (!authenticated) {
      setRecords(null);
      setExpanded(false);
      setFailure(false);
    }
  }, [authenticated]);

  const review = async () => {
    if (!authenticated || loading) return;
    setExpanded(true);
    setLoading(true);
    setRecords(null);
    setFailure(false);
    try {
      const response = await apiClient.get<{ requests: RetiredCredentialDeletion[] }>(
        '/api/channels/personal/consent-recovery/deletion-requests',
      );
      setRecords(parseRetiredCredentialDeletions(response));
    } catch {
      setFailure(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="space-y-3 border-t border-border/60 pt-4"
      aria-label="Retired provider deletion history">
      <p className="text-sm font-semibold">Credential deletion request history</p>
      <p className="text-xs text-muted-foreground">
        Review retained Karen deletion requests after a provider or channel host
        is retired. A vendor claim does not prove remote unlink, credential erasure,
        deletion of retained messages, or permission to purge the connection.
      </p>
      <Button type="button" size="sm" variant="outline"
        aria-label="Review credential deletion requests"
        disabled={!authenticated || loading}
        onClick={() => void review()}>
        {expanded ? 'Refresh deletion request history' : 'Review deletion requests'}
      </Button>
      {loading && <p role="status" className="text-sm">Reading the deletion request ledger...</p>}
      {!loading && failure && authenticated && (
        <Alert role="alert" variant="destructive">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Deletion request status unavailable</AlertTitle>
          <AlertDescription>
            Karen could not verify your retained deletion requests. No deletion was performed.
          </AlertDescription>
        </Alert>
      )}
      {!loading && authenticated && records?.length === 0 && (
        <p role="status" className="text-xs text-muted-foreground">
          No retained deletion requests were found. This is not proof that provider data
          or credentials do not exist.
        </p>
      )}
      {!loading && authenticated && records && records.length > 0 && (
        <div className="space-y-3">
          {records.map((record) => (
            <div key={record.request_id}
              className="space-y-1 rounded-md border border-border/60 p-3">
              <p className="break-all text-sm font-semibold">{record.provider_id}</p>
              <p className="break-all text-xs text-muted-foreground">
                Connection {record.connection_id}, revision {record.connection_revision}
              </p>
              <p className="text-xs">{deletionStatusDescription[record.status]}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function ChannelsSettings() {
  const { user, isAuthenticated, isLoading: isAuthLoading } = useAuth();
  const principalKey = isAuthenticated && user?.tenant_id && user?.user_id
    ? user.tenant_id + ':' + user.user_id
    : 'signed-out';
  const [inventory, setInventory] = useState<PersonalChannel[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setInventory(null);
    setError(null);

    if (isAuthLoading) {
      return () => {
        cancelled = true;
      };
    }
    if (!isAuthenticated) {
      setLoading(false);
      setError('Sign in to view your assigned channel connections.');
      return () => {
        cancelled = true;
      };
    }

    setLoading(true);
    void apiClient
      .get<ChannelInventoryResponse>('/api/channels/personal/connections')
      .then((response) => {
        const connections = parseInventory(response);
        if (!cancelled) {
          setInventory(connections);
          setError(null);
        }
      })
      .catch((failure: unknown) => {
        if (!cancelled) {
          setInventory(null);
          setError(readableFailure(failure));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, isAuthLoading, reload, principalKey]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Review the connections assigned to your account. Karen reports stored
          channel evidence separately from verified live connectivity.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={loading || isAuthLoading || !isAuthenticated}
          onClick={() => setReload((current) => current + 1)}
          aria-label="Refresh channel inventory"
        >
          {loading ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
          )}
          Refresh
        </Button>
      </div>

      <Alert role="note">
        <ShieldAlert className="h-4 w-4" aria-hidden="true" />
        <AlertTitle>Read-only channel status</AlertTitle>
        <AlertDescription>
          This panel does not initiate personal WhatsApp Linked Devices pairing,
          issue QR codes, unlink sessions, or erase provider credentials.
          A configured provider is not proof of a live connection. The official
          WhatsApp Business Cloud API remains a separate channel.
        </AlertDescription>
      </Alert>

      {(loading || isAuthLoading) && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Checking assigned channel connections...
        </p>
      )}

      {!loading && !isAuthLoading && error && (
        <Alert variant="destructive" role="alert">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Channel status unavailable</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!loading && !isAuthLoading && inventory?.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">No assigned personal connections</CardTitle>
            <CardDescription>
              The Channels backend reported no channel connections assigned to
              your authenticated account. This does not indicate whether a provider
              is installed or operational.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {!loading && !isAuthLoading && inventory && inventory.length > 0 && (
        <div className="space-y-3" aria-label="Your channel connections">
          {inventory.map((channel) => (
            <Card key={channel.connection_id}>
              <CardHeader>
                <CardTitle className="text-base">{channel.installation_id}</CardTitle>
                <CardDescription className="break-all">
                  Connection {channel.connection_id}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p>
                  <strong>Provider configuration:</strong>{' '}
                  {channel.availability === 'configured'
                    ? 'Registered in Karen, not verified live'
                    : 'Unavailable'}
                </p>
                <p>
                  <strong>Live session:</strong>{' '}
                  {channel.live_connected
                    ? 'Reported connected by Karen'
                    : 'Not verified connected'}
                </p>
                <p>
                  <strong>QR available:</strong>{' '}
                  {channel.qr_available ? 'Reported available by Karen' : 'No'}
                </p>
                {channel.last_observed_phase && (
                  <p>
                    <strong>Last persisted provider event:</strong>{' '}
                    {channel.last_observed_phase} (historical, not a health check)
                  </p>
                )}
                {channel.provider_unlinked && (
                  <p>
                    A provider unlink observation was recorded. This is not proof
                    of credential or message-data erasure.
                  </p>
                )}
                {channel.availability === 'configured' && channel.provider_id && (
                  <PersonalChannelRiskConsent
                    connectionId={channel.connection_id}
                    providerId={channel.provider_id}
                    allowAcknowledgement
                  />
                )}
                {channel.active_consent_provider_ids
                  .filter((providerId) =>
                    channel.availability !== 'configured' ||
                    providerId !== channel.provider_id,
                  )
                  .map((providerId) => (
                    <PersonalChannelRiskConsent
                      key={providerId}
                      connectionId={channel.connection_id}
                      providerId={providerId}
                      allowAcknowledgement={false}
                    />
                  ))}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      <RetiredPersonalConsentRecovery
        key={principalKey}
        channels={inventory}
        authenticated={isAuthenticated && !isAuthLoading}
      />
      <RetiredCredentialDeletionHistory
        key={principalKey}
        authenticated={isAuthenticated && !isAuthLoading}
      />
    </div>
  );
}
