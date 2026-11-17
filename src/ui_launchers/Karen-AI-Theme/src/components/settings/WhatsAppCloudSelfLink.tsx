'use client';

/**
 * KWA-01C6C2B2: one-time, consumer-accessible WhatsApp Cloud self-link UX.
 *
 * Only the canonical authenticated ChannelHost may issue a link challenge.
 * A returned /link command is not evidence of provider delivery or identity
 * binding. Never persist the command, copy it automatically, or log it.
 */
import { useEffect, useRef, useState } from 'react';
import { AlertCircle, Copy, Loader2, RefreshCw, ShieldCheck } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ApiError, apiClient } from '@/lib/api';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const COMMAND = /^\/link [A-Za-z0-9_-]{43}$/;

type WhatsAppConnectionChoice = Readonly<{
  connection_id: string;
  connection_revision: number;
}>;

function validateConnectionChoices(value: unknown): WhatsAppConnectionChoice[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Unverified WhatsApp connection inventory');
  }
  const source = value as Record<string, unknown>;
  if (Object.keys(source).length !== 1 || !Array.isArray(source.connections) ||
    source.connections.length > 50) {
    throw new Error('Unverified WhatsApp connection inventory');
  }
  const ids = new Set<string>();
  const result: WhatsAppConnectionChoice[] = [];
  for (const item of source.connections) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      throw new Error('Unverified WhatsApp connection inventory');
    }
    const row = item as Record<string, unknown>;
    if (Object.keys(row).length !== 2 ||
      typeof row.connection_id !== 'string' || !UUID.test(row.connection_id) ||
      typeof row.connection_revision !== 'number' ||
      !Number.isSafeInteger(row.connection_revision) || row.connection_revision < 1 ||
      ids.has(row.connection_id)) {
      throw new Error('Unverified WhatsApp connection inventory');
    }
    ids.add(row.connection_id);
    result.push({
      connection_id: row.connection_id,
      connection_revision: row.connection_revision,
    });
  }
  return result;
}

function describeInventoryFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Sign in to view your WhatsApp Cloud connection choices.';
    if (error.status === 403) return 'Your account cannot list WhatsApp Cloud connections.';
  }
  return 'Karen could not verify your available WhatsApp Cloud connections.';
}

type IssuedChallenge = Readonly<{
  challenge_id: string;
  command: string;
  expires_in_seconds: number;
}>;

type ChallengeStatus = Readonly<{
  challenge_id: string;
  status: 'pending' | 'consumed' | 'revoked' | 'expired' | 'invalidated';
}>;

function validateStatus(value: unknown, challengeId: string): ChallengeStatus {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid link challenge status');
  }
  const data = value as Record<string, unknown>;
  if (
    Object.keys(data).length !== 5 ||
    data.challenge_id !== challengeId ||
    data.evidence_basis !== 'host_link_challenge_ledger' ||
    data.current_binding_verified !== false ||
    data.delivery_verified !== false ||
    !['pending', 'consumed', 'revoked', 'expired', 'invalidated'].includes(
      String(data.status),
    )
  ) {
    throw new Error('Unverified link challenge status');
  }
  return { challenge_id: challengeId, status: data.status as ChallengeStatus['status'] };
}

function statusMessage(status: ChallengeStatus['status']): string {
  switch (status) {
    case 'pending':
      return 'Karen has not recorded a consumed proof. Send the command from your sender before it expires, then check again.';
    case 'consumed':
      return 'Karen recorded successful one-time proof consumption through signed channel ingress. This is historical evidence, not confirmation of a currently active sender binding, ChatRuntime reply or delivery.';
    case 'revoked':
      return 'This one-time proof was superseded or revoked. Request another command if your sender is not linked.';
    case 'expired':
      return 'This proof expired without recorded consumption. Request a new command to try again.';
    case 'invalidated':
      return 'The connection was disabled or its revision changed. Ask your operator to verify the connection before retrying.';
  }
}

function validateChallenge(value: unknown): IssuedChallenge {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid identity challenge response');
  }
  const entry = value as Record<string, unknown>;
  if (
    Object.keys(entry).length !== 3 ||
    typeof entry.challenge_id !== 'string' ||
    !UUID.test(entry.challenge_id) ||
    typeof entry.command !== 'string' ||
    !COMMAND.test(entry.command) ||
    typeof entry.expires_in_seconds !== 'number' ||
    !Number.isSafeInteger(entry.expires_in_seconds) ||
    entry.expires_in_seconds < 60 ||
    entry.expires_in_seconds > 900
  ) {
    throw new Error('Unverified identity challenge response');
  }
  // The challenge ID is only for the host's durable ledger; it is not a
  // permission or a consumer-facing provider status.
  return {
    challenge_id: entry.challenge_id,
    command: entry.command,
    expires_in_seconds: entry.expires_in_seconds,
  };
}

function describeFailure(error: unknown, statusRequest = false): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Sign in again to request an identity link.';
    if (error.status === 403) return 'Your account or this connection is not authorized for identity linking.';
    if (error.status === 404) return statusRequest
      ? 'This link challenge was not found for your verified account.'
      : 'The requested WhatsApp connection was not found.';
    if (error.status === 409) return 'The connection changed. Ask the operator to verify its current state.';
    if (error.status === 422) return 'The connection ID was not accepted.';
    if (error.status === 503) return 'Identity linking is unavailable. No command was verified.';
  }
  return 'Karen could not verify the identity-link request. No link is confirmed.';
}

export default function WhatsAppCloudSelfLink() {
  const [connectionId, setConnectionId] = useState('');
  const [connectionChoices, setConnectionChoices] = useState<WhatsAppConnectionChoice[] | null>(null);
  const [inventoryPending, setInventoryPending] = useState(false);
  const [inventoryError, setInventoryError] = useState<string | null>(null);
  const inventoryEpoch = useRef(0);
  const [issued, setIssued] = useState<IssuedChallenge | null>(null);
  const [lastChallengeId, setLastChallengeId] = useState<string | null>(null);
  const [lastStatus, setLastStatus] = useState<ChallengeStatus | null>(null);
  const [statusPending, setStatusPending] = useState(false);
  const [pending, setPending] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestEpoch = useRef(0);

  // The parent keys and unmounts this panel on signed-in principal changes.
  // Drop stale responses on unmount and erase the token after its TTL.
  useEffect(() => () => {
    requestEpoch.current += 1;
    inventoryEpoch.current += 1;
  }, []);
  useEffect(() => {
    if (issued === null) return;
    const clear = window.setTimeout(() => {
      // An in-flight status read made before expiry cannot revive "pending"
      // after the local command has already reached its declared lifetime.
      requestEpoch.current += 1;
      setIssued(null);
      setCopied(false);
      setLastStatus(null);
      setStatusPending(false);
    }, issued.expires_in_seconds * 1000);
    return () => window.clearTimeout(clear);
  }, [issued]);

  const clearCommand = () => {
    requestEpoch.current += 1;
    setIssued(null);
    setLastChallengeId(null);
    setLastStatus(null);
    setStatusPending(false);
    setCopied(false);
    setError(null);
  };

  const changeConnection = (nextValue: string) => {
    clearCommand();
    setConnectionId(nextValue.trim());
  };

  const refreshConnectionChoices = async () => {
    if (inventoryPending) return;
    const epoch = ++inventoryEpoch.current;
    setInventoryPending(true);
    setInventoryError(null);
    setConnectionChoices(null);
    try {
      const response = await apiClient.get<unknown>(
        '/api/channels/identity/whatsapp/connections',
      );
      const verified = validateConnectionChoices(response);
      if (inventoryEpoch.current === epoch) setConnectionChoices(verified);
    } catch (failure) {
      if (inventoryEpoch.current === epoch) {
        setInventoryError(describeInventoryFailure(failure));
      }
    } finally {
      if (inventoryEpoch.current === epoch) setInventoryPending(false);
    }
  };

  const issueChallenge = async () => {
    const id = connectionId;
    if (pending || !UUID.test(id)) return;

    const epoch = ++requestEpoch.current;
    setIssued(null);
    setLastChallengeId(null);
    setLastStatus(null);
    setStatusPending(false);
    setCopied(false);
    setError(null);
    setPending(true);
    try {
      const result = await apiClient.post<unknown>(
        `/api/channels/identity/whatsapp/connections/${id}/challenge`,
        {},
      );
      const verified = validateChallenge(result);
      if (requestEpoch.current === epoch) {
        setLastChallengeId(verified.challenge_id);
        setIssued(verified);
      }
    } catch (failure) {
      if (requestEpoch.current === epoch) setError(describeFailure(failure));
    } finally {
      if (requestEpoch.current === epoch) setPending(false);
    }
  };

  const inspectStatus = async () => {
    const id = connectionId;
    const challengeId = lastChallengeId;
    if (statusPending || pending || !UUID.test(id) || !challengeId) return;
    const epoch = ++requestEpoch.current;
    setLastStatus(null);
    setStatusPending(true);
    setError(null);
    try {
      const result = await apiClient.get<unknown>(
        `/api/channels/identity/whatsapp/connections/${id}/challenges/${challengeId}/status`,
      );
      const inspected = validateStatus(result, challengeId);
      if (requestEpoch.current === epoch) {
        setLastStatus(inspected);
        if (inspected.status !== 'pending') {
          // A consumed, expired, revoked or invalidated bearer proof must
          // never remain rendered or copyable after observation.
          setIssued(null);
          setCopied(false);
        }
      }
    } catch (failure) {
      if (requestEpoch.current === epoch) setError(describeFailure(failure, true));
    } finally {
      if (requestEpoch.current === epoch) setStatusPending(false);
    }
  };

  const copyCommand = async () => {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.command);
      setCopied(true);
    } catch {
      setCopied(false);
      setError('Clipboard permission was denied. Select and copy the one-time command manually.');
    }
  };

  return (
    <Card role="region" aria-label="WhatsApp Cloud account linking">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck aria-hidden="true" className="h-4 w-4" />
          Link your WhatsApp Cloud sender
        </CardTitle>
        <CardDescription>
          Choose a configured WhatsApp Business Cloud API connection in your
          tenant, or enter a connection ID provided by an authorized operator.
          Then request a one-time command for your verified Karen account.
          This is separate from personal WhatsApp Linked Devices pairing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void refreshConnectionChoices()}
            disabled={inventoryPending}
          >
            {inventoryPending
              ? <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />
              : <RefreshCw aria-hidden="true" className="mr-2 h-4 w-4" />}
            Find available WhatsApp Cloud connections
          </Button>
          <p className="text-xs text-muted-foreground">
            Only enabled connections in your verified Karen tenant are returned.
            This inventory does not establish live Meta connectivity.
          </p>
          {inventoryError && (
            <p role="alert" className="text-xs text-destructive">{inventoryError}</p>
          )}
          {connectionChoices && connectionChoices.length === 0 && (
            <p role="status" className="text-xs text-muted-foreground">
              Karen returned no enabled WhatsApp Cloud connections for your account.
              Ask your operator to configure and enable one before linking.
            </p>
          )}
          {connectionChoices && connectionChoices.length > 0 && (
            <div className="space-y-2">
              <Label htmlFor="whatsapp-self-link-available">Available connections</Label>
              <select
                id="whatsapp-self-link-available"
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={connectionChoices.some((entry) => entry.connection_id === connectionId)
                  ? connectionId : ''}
                onChange={(event) => changeConnection(event.target.value)}
                disabled={pending}
              >
                <option value="">Select a connection</option>
                {connectionChoices.map((entry) => (
                  <option key={entry.connection_id} value={entry.connection_id}>
                    {entry.connection_id} (revision {entry.connection_revision})
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">
                An enabled host connection is not confirmation that Meta can send or receive.
              </p>
            </div>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="whatsapp-self-link-connection">Operator-provided connection ID</Label>
          <Input
            id="whatsapp-self-link-connection"
            value={connectionId}
            onChange={(event) => changeConnection(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder="WhatsApp Cloud connection UUID"
            maxLength={36}
            disabled={pending}
          />
        </div>
        <Button
          type="button"
          disabled={pending || !UUID.test(connectionId)}
          onClick={() => void issueChallenge()}
        >
          {pending && <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />}
          Request one-time link command
        </Button>
        {error && (
          <Alert variant="destructive" role="alert">
            <AlertCircle aria-hidden="true" className="h-4 w-4" />
            <AlertTitle>Link request not verified</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {issued && (
          <div className="space-y-3 rounded-md border border-border/60 p-3">
            <p className="text-sm font-semibold">One-time command issued by Karen</p>
            <p className="text-xs text-muted-foreground">
              Send this exact command from your own WhatsApp test sender to your
              operator-approved WhatsApp Business test number within{' '}
              {Math.ceil(issued.expires_in_seconds / 60)} minutes.
              Treat it as a secret. Never post it in screenshots, logs or support tickets.
            </p>
            <code
              aria-label="One-time WhatsApp link command"
              className="block select-all break-all rounded bg-muted p-2 font-mono text-xs"
            >
              {issued.command}
            </code>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm"
                onClick={() => void copyCommand()}>
                <Copy aria-hidden="true" className="mr-2 h-4 w-4" />
                Copy command
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={clearCommand}>
                Clear command from screen
              </Button>
            </div>
            {copied && (
              <p role="status" className="text-xs text-muted-foreground">
                Copied. Clear your clipboard after sending the command.
              </p>
            )}
            <p className="text-xs font-medium">
              Command issued does not mean the sender is linked. Karen must independently
              verify a real, signed provider message and bind your sender identity.
              Live ChatRuntime and delivery remain unverified here.
            </p>
          </div>
        )}
        {lastChallengeId && (
          <div className="space-y-2 rounded-md border border-border/60 p-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={statusPending || pending}
              onClick={() => void inspectStatus()}
            >
              {statusPending &&
                <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />}
              Check link proof status
            </Button>
            {lastStatus && (
              <p role="status" className="text-xs" data-link-proof-status={lastStatus.status}>
                {statusMessage(lastStatus.status)}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              This checks only Karen&apos;s own one-time challenge ledger. It does
              not independently verify Meta origin, the current sender binding,
              a ChatRuntime reply, or delivery.
            </p>
          </div>
        )}
        {!issued && !lastChallengeId && (
          <p className="text-xs text-muted-foreground">
            A new challenge replaces any previous unused challenge for this
            account and connection. No provider delivery or linked status is
            asserted by this screen.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
