'use client';

/**
 * KOC-05: read-only, backend-owned personal channel inventory.
 *
 * Only the canonical ChannelHost may report an assigned connection or its
 * evidence status. This panel never initiates pairing, infers provider health,
 * manufactures a QR, or treats the last stored event as a live session.
 */

import { useEffect, useState } from 'react';
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

      <Alert>
        <ShieldAlert className="h-4 w-4" aria-hidden="true" />
        <AlertTitle>Personal WhatsApp pairing is not available</AlertTitle>
        <AlertDescription>
          Unofficial personal Linked Devices pairing has not passed managed-provider
          and live session verification. The official WhatsApp Business Cloud API
          is a separate channel. No QR code, connect, or disconnect operation is
          available in this panel.
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
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
