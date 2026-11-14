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

export default function ChannelsSettings() {
  const { isAuthenticated, isLoading: isAuthLoading } = useAuth();
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
  }, [isAuthenticated, isAuthLoading, reload]);

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
    </div>
  );
}
