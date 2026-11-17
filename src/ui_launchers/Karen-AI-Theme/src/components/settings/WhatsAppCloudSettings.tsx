'use client';

/**
 * Governed WhatsApp Cloud operator lifecycle.
 *
 * The browser never chooses adapters, policy grants or tenants, never stores
 * Vault credentials, and never infers provider connectivity from a DB flag.
 * All mutations and inventory reads are owned by the authenticated host API.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Loader2, RefreshCw, ShieldCheck } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ApiError, apiClient } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';
import WhatsAppCloudTrialEvidence from './WhatsAppCloudTrialEvidence';

const ENDPOINT = '/api/channels/operator/whatsapp/connections';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PHONE_ID_PATTERN = /^[0-9]{1,32}$/;

type ConnectionState = {
  connection_id: string;
  connection_revision: number;
  enabled: boolean;
};
type OperationStage = 'provisioned' | 'activated' | 'deactivated';

function parseConnections(value: unknown): ConnectionState[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid WhatsApp operator inventory');
  }
  const record = value as Record<string, unknown>;
  if (
    Object.keys(record).some((key) => key !== 'connections') ||
    !Array.isArray(record.connections) || record.connections.length > 50
  ) {
    throw new Error('Invalid WhatsApp operator inventory');
  }
  const connections = record.connections;
  const seen = new Set<string>();
  return connections.map((item: unknown) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      throw new Error('Invalid WhatsApp operator connection');
    }
    const connection = item as Record<string, unknown>;
    if (
      Object.keys(connection).some((key) =>
        !['connection_id', 'connection_revision', 'enabled'].includes(key)) ||
      typeof connection.connection_id !== 'string' ||
      !UUID_PATTERN.test(connection.connection_id) ||
      seen.has(connection.connection_id) ||
      typeof connection.connection_revision !== 'number' ||
      !Number.isSafeInteger(connection.connection_revision) ||
      connection.connection_revision < 1 ||
      typeof connection.enabled !== 'boolean'
    ) {
      throw new Error('Invalid WhatsApp operator connection');
    }
    seen.add(connection.connection_id);
    return {
      connection_id: connection.connection_id,
      connection_revision: connection.connection_revision,
      enabled: connection.enabled,
    };
  });
}

function parseOperation(
  value: unknown, stage: OperationStage, expectedConnectionId?: string,
): ConnectionState {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid WhatsApp operator response');
  }
  const record = value as Record<string, unknown>;
  if (
    Object.keys(record).some((key) => ![
      'connection_id', 'connection_revision', 'enabled', 'stage',
      'provider_phone_verified', 'webhook_subscription_verified',
      'signed_inbound_verified', 'delivery_verified',
    ].includes(key)) ||
    record.stage !== stage ||
    typeof record.connection_id !== 'string' ||
    !UUID_PATTERN.test(record.connection_id) ||
    (expectedConnectionId && record.connection_id !== expectedConnectionId) ||
    typeof record.connection_revision !== 'number' ||
    !Number.isSafeInteger(record.connection_revision) ||
    record.connection_revision < 1 ||
    record.enabled !== (stage === 'activated') ||
    record.provider_phone_verified !== (stage === 'activated') ||
    record.webhook_subscription_verified !== false ||
    record.signed_inbound_verified !== false ||
    record.delivery_verified !== false
  ) {
    throw new Error('Unverified WhatsApp operator response');
  }
  return {
    connection_id: record.connection_id,
    connection_revision: record.connection_revision,
    enabled: record.enabled,
  };
}

function readableError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Sign in to manage WhatsApp Cloud connections.';
    if (error.status === 403) return 'Your account is not authorized to manage WhatsApp Cloud.';
    if (error.status === 409) return 'Connection changed. Refresh the inventory before retrying.';
    if (error.status === 422) return 'The connection details or revision were rejected.';
    if (error.status === 503) return 'WhatsApp Cloud host is unavailable. No change is verified.';
  }
  return 'Karen could not verify the WhatsApp operation. Refresh before retrying.';
}

export default function WhatsAppCloudSettings() {
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const principal = [
    String(user?.tenant_id ?? ''),
    String(user?.user_id ?? ''),
  ].join(':');
  const authenticated = isAuthenticated && !authLoading;
  const generation = useRef(0);
  const [connections, setConnections] = useState<ConnectionState[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [phoneNumberId, setPhoneNumberId] = useState('');
  const [credentialHandle, setCredentialHandle] = useState('');

  const refresh = useCallback(async () => {
    const currentGeneration = generation.current;
    setConnections(null);
    setError(null);
    setLoading(true);
    try {
      const response = await apiClient.get<unknown>(ENDPOINT);
      const verified = parseConnections(response);
      if (generation.current === currentGeneration) {
        setConnections(verified);
      }
    } catch (failure) {
      if (generation.current === currentGeneration) {
        setError(readableError(failure));
      }
    } finally {
      if (generation.current === currentGeneration) setLoading(false);
    }
  }, []);

  useEffect(() => {
    generation.current += 1;
    setConnections(null);
    setError(null);
    setNotice(null);
    setPending(null);
    setPhoneNumberId('');
    setCredentialHandle('');
    if (authenticated) {
      void refresh();
    }
    return () => { generation.current += 1; };
  }, [authenticated, principal, refresh]);

  const run = async (
    stage: OperationStage,
    connection?: ConnectionState,
  ) => {
    if (!authenticated || pending || loading) return;
    const revision = connection?.connection_revision;
    const id = connection?.connection_id;
    if (stage === 'provisioned' && (
      !PHONE_ID_PATTERN.test(phoneNumberId) ||
      credentialHandle.trim().length < 1 ||
      credentialHandle.length > 256
    )) {
      setError('Enter the numeric Meta phone-number ID and an existing opaque Vault handle.');
      return;
    }
    if (stage !== 'provisioned' && (!id || !revision)) return;

    const currentGeneration = generation.current;
    setPending(id ?? 'provision');
    setError(null);
    setNotice(null);
    try {
      const url = stage === 'provisioned' ? ENDPOINT :
        `${ENDPOINT}/${id}/${stage === 'activated' ? 'activate' : 'deactivate'}`;
      const payload = stage === 'provisioned' ?
        { provider_account_id: phoneNumberId, credential_handle: credentialHandle.trim() } :
        { expected_revision: revision };
      const response = await apiClient.post<unknown>(url, payload);
      parseOperation(response, stage, id);
      if (generation.current !== currentGeneration) return;
      if (stage === 'provisioned') {
        setPhoneNumberId('');
        setCredentialHandle('');
        setNotice('Account provisioned as disabled. Activation and webhook verification are separate.');
      } else if (stage === 'activated') {
        setNotice('Meta phone identity checked and connection enabled locally. Webhook and delivery remain unverified.');
      } else {
        setNotice('Connection disabled in Karen. External Meta subscription removal is not verified.');
      }
      await refresh();
    } catch (failure) {
      if (generation.current === currentGeneration) {
        setConnections(null);
        setError(readableError(failure));
      }
    } finally {
      if (generation.current === currentGeneration) setPending(null);
    }
  };

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck aria-hidden="true" className="h-5 w-5" />
            WhatsApp Cloud operator setup
          </CardTitle>
          <CardDescription>
            Official Meta Cloud API transport. Karen controls installation, permissions,
            secrets and execution. Provisioning does not subscribe a webhook or deliver a message.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="whatsapp-cloud-phone-id">Meta phone-number ID</Label>
              <Input
                id="whatsapp-cloud-phone-id"
                value={phoneNumberId}
                onChange={(event) => setPhoneNumberId(event.target.value)}
                inputMode="numeric"
                autoComplete="off"
                placeholder="Numeric phone-number ID"
                maxLength={32}
                disabled={!authenticated || Boolean(pending)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="whatsapp-cloud-vault-handle">Existing Vault credential handle</Label>
              <Input
                id="whatsapp-cloud-vault-handle"
                value={credentialHandle}
                onChange={(event) => setCredentialHandle(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                placeholder="Opaque tenant-scoped Vault reference"
                maxLength={256}
                disabled={!authenticated || Boolean(pending)}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Reference a previously approved tenant Vault bundle. Do not paste a Meta access token,
            app secret, or webhook verify token into either field.
          </p>
          <Button
            disabled={!authenticated || loading || Boolean(pending) ||
              !PHONE_ID_PATTERN.test(phoneNumberId) || !credentialHandle.trim()}
            onClick={() => { void run('provisioned'); }}
          >
            {pending === 'provision' && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Provision disabled account
          </Button>
        </CardContent>
      </Card>

      {(!authenticated && !authLoading) && (
        <Alert role="alert" variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Sign-in required</AlertTitle>
          <AlertDescription>Sign in with an authorized operator account.</AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert role="alert" variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Operation not verified</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {notice && (
        <Alert role="status">
          <AlertTitle>Backend response confirmed</AlertTitle>
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle>Tenant WhatsApp connections</CardTitle>
              <CardDescription>
                Persisted Karen state only, not a live Meta webhook or delivery health check.
              </CardDescription>
            </div>
            <Button
              size="sm" variant="outline"
              disabled={!authenticated || loading || Boolean(pending)}
              onClick={() => { void refresh(); }}
              aria-label="Refresh WhatsApp Cloud inventory"
            >
              <RefreshCw aria-hidden="true" className="mr-2 h-4 w-4" />
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {(loading || authLoading) && (
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Checking backend connection state
            </p>
          )}
          {connections?.length === 0 && (
            <p className="text-sm text-muted-foreground">No WhatsApp Cloud connections found for this tenant.</p>
          )}
          {connections?.map((connection) => (
            <div key={connection.connection_id} className="rounded-lg border p-4 space-y-3">
              <div>
                <p className="break-all font-mono text-xs">{connection.connection_id}</p>
                <p className="mt-1 text-sm font-medium">
                  {connection.enabled ? 'Enabled in Karen (live status unverified)' : 'Disabled in Karen'}
                </p>
                <p className="text-xs text-muted-foreground">
                  Persisted revision {connection.connection_revision}. Signed webhook and delivery unverified.
                </p>
              </div>
              <Button
                variant={connection.enabled ? 'destructive' : 'default'}
                disabled={!authenticated || Boolean(pending) || loading}
                onClick={() => {
                  void run(connection.enabled ? 'deactivated' : 'activated', connection);
                }}
              >
                {pending === connection.connection_id && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                {connection.enabled ? 'Deactivate connection' : 'Activate connection'}
              </Button>
              <WhatsAppCloudTrialEvidence
                key={principal + ':' + connection.connection_id}
                connectionId={connection.connection_id}
              />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
