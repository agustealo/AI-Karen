'use client';

/**
 * @file PrivacySettings.tsx
 * @description Live backend-governed privacy controls for export, erasure,
 * request status, and verified request processing.
 *
 * Privacy authority:
 * - Backend owns RBAC, tenant isolation, verification, audit, export, erasure,
 *   and processing.
 * - UI only submits scoped requests and displays backend responses.
 * - Do not fake privacy completion or infer permission locally.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Eye,
  EyeOff,
  FileDown,
  FileWarning,
  Info,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { useToast } from '@/hooks/use-toast';
import { ApiError, apiClient } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';

type PrivacyHealth = {
  status: string;
  service: string;
  features: Record<string, boolean>;
  timestamp: string;
};

type PrivacyRequestResponse = {
  request_id: string;
  status: string;
  verification_token: string;
  estimated_completion: string;
  next_steps: string;
};

type PrivacyRequestStatusResponse = {
  request_id: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
  progress: Record<string, unknown>;
};

type PrivacyAction =
  | 'health'
  | 'export'
  | 'erasure'
  | 'status'
  | 'process';

type AccessDeniedState = Partial<Record<PrivacyAction, boolean>>;

const PRIVACY_HEALTH_ENDPOINT = '/api/privacy/health';
const PRIVACY_EXPORT_ENDPOINT = '/api/privacy/export/request';
const PRIVACY_ERASURE_ENDPOINT = '/api/privacy/erasure/request';

const DEFAULT_DATA_TYPES = 'all';
const DEFAULT_EXPORT_FORMAT = 'json';
const DEFAULT_ERASURE_TYPE = 'soft_delete';

function cleanString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function splitCsv(value: string): string[] {
  const seen = new Set<string>();

  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => {
      const normalized = item.toLowerCase();

      if (!item || seen.has(normalized)) {
        return false;
      }

      seen.add(normalized);
      return true;
    });
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message.trim()) {
    return error.message.trim();
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }

  if (typeof error === 'string' && error.trim()) {
    return error.trim();
  }

  return fallback;
}

function getSafeDateTimeLabel(value: unknown): string {
  const rawDate = cleanString(value);

  if (!rawDate) {
    return 'Unknown';
  }

  const parsed = new Date(rawDate);

  if (Number.isNaN(parsed.getTime())) {
    return rawDate;
  }

  return parsed.toLocaleString();
}

function normalizeRequestId(value: string): string {
  return value.trim();
}

function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

function isAccessDeniedError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

export default function PrivacySettings() {
  const { toast } = useToast();
  const { user, isAuthenticated } = useAuth();

  const [health, setHealth] = useState<PrivacyHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [isLoadingHealth, setIsLoadingHealth] = useState(true);

  const [userId, setUserId] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [dataTypes, setDataTypes] = useState(DEFAULT_DATA_TYPES);
  const [exportFormat, setExportFormat] = useState(DEFAULT_EXPORT_FORMAT);
  const [confirmationToken, setConfirmationToken] = useState('');
  const [requestId, setRequestId] = useState('');
  const [verificationToken, setVerificationToken] = useState('');
  const [erasureType, setErasureType] = useState(DEFAULT_ERASURE_TYPE);
  const [showVerificationToken, setShowVerificationToken] = useState(false);

  const [isSubmittingExport, setIsSubmittingExport] = useState(false);
  const [isSubmittingErasure, setIsSubmittingErasure] = useState(false);
  const [isLoadingStatus, setIsLoadingStatus] = useState(false);
  const [isProcessingRequest, setIsProcessingRequest] = useState(false);

  const [authRequired, setAuthRequired] = useState(false);
  const [accessDenied, setAccessDenied] = useState<AccessDeniedState>({});

  const [lastRequest, setLastRequest] =
    useState<PrivacyRequestResponse | null>(null);
  const [requestStatus, setRequestStatus] =
    useState<PrivacyRequestStatusResponse | null>(null);

  useEffect(() => {
    if (!user) {
      return;
    }

    const nextUserId = cleanString(user.user_id);
    const nextTenantId = cleanString(user.tenant_id);

    if (nextUserId) {
      setUserId(nextUserId);
    }

    if (nextTenantId) {
      setTenantId(nextTenantId);
    }
  }, [user]);

  const parsedDataTypes = useMemo(() => {
    const parsed = splitCsv(dataTypes);

    return parsed.length > 0 ? parsed : [DEFAULT_DATA_TYPES];
  }, [dataTypes]);

  const privacyServiceFeatures = useMemo(() => {
    return health?.features && typeof health.features === 'object'
      ? Object.entries(health.features)
      : [];
  }, [health]);

  const canSubmitScopedRequest =
    Boolean(userId.trim()) && Boolean(isAuthenticated) && !authRequired;

  const setActionAccessDenied = useCallback(
    (action: PrivacyAction, denied: boolean) => {
      setAccessDenied((current) => ({
        ...current,
        [action]: denied,
      }));
    },
    [],
  );

  const handleRequestError = useCallback(
    (
      error: unknown,
      action: PrivacyAction,
      title: string,
      fallbackDescription: string,
    ) => {
      if (isAuthError(error)) {
        setAuthRequired(true);
        return;
      }

      if (isAccessDeniedError(error)) {
        setActionAccessDenied(action, true);
        return;
      }

      toast({
        title,
        description: getErrorMessage(error, fallbackDescription),
        variant: 'destructive',
      });
    },
    [setActionAccessDenied, toast],
  );

  const loadHealth = useCallback(async () => {
    setIsLoadingHealth(true);

    try {
      const response = await apiClient.get<PrivacyHealth>(PRIVACY_HEALTH_ENDPOINT);
      setHealth(response);
      setAuthRequired(false);
      setHealthError(null);
      setActionAccessDenied('health', false);
    } catch (error) {
      setHealth(null);

      if (isAuthError(error)) {
        setAuthRequired(true);
        setHealthError(null);
      } else if (isAccessDeniedError(error)) {
        setActionAccessDenied('health', true);
        setHealthError(null);
      } else {
        setAuthRequired(false);
        setHealthError(
          getErrorMessage(error, 'Karen could not load privacy service health.'),
        );
      }
    } finally {
      setIsLoadingHealth(false);
    }
  }, [setActionAccessDenied]);

  useEffect(() => {
    let mounted = true;

    const guardedLoad = async () => {
      if (!mounted) {
        return;
      }

      await loadHealth();
    };

    void guardedLoad();

    return () => {
      mounted = false;
    };
  }, [loadHealth]);

  const handleRequestExport = useCallback(async () => {
    const scopedUserId = userId.trim();

    if (!scopedUserId) {
      return;
    }

    setIsSubmittingExport(true);
    setAuthRequired(false);
    setActionAccessDenied('export', false);

    try {
      const response = await apiClient.post<PrivacyRequestResponse>(
        PRIVACY_EXPORT_ENDPOINT,
        {
          user_id: scopedUserId,
          tenant_id: tenantId.trim() || null,
          data_types: parsedDataTypes,
          export_format: exportFormat.trim() || DEFAULT_EXPORT_FORMAT,
          include_pii: false,
        },
      );

      setLastRequest(response);
      setRequestStatus(null);
      setRequestId(response.request_id);
      setVerificationToken(response.verification_token);
      setShowVerificationToken(false);

      toast({
        title: 'Export request created',
        description: `Privacy request ${response.request_id} is pending backend processing.`,
      });
    } catch (error) {
      handleRequestError(
        error,
        'export',
        'Export request failed',
        'Karen could not submit the privacy export request.',
      );
    } finally {
      setIsSubmittingExport(false);
    }
  }, [
    exportFormat,
    handleRequestError,
    parsedDataTypes,
    setActionAccessDenied,
    tenantId,
    toast,
    userId,
  ]);

  const handleRequestErasure = useCallback(async () => {
    const scopedUserId = userId.trim();
    const token = confirmationToken.trim();

    if (!scopedUserId || !token) {
      return;
    }

    setIsSubmittingErasure(true);
    setAuthRequired(false);
    setActionAccessDenied('erasure', false);

    try {
      const response = await apiClient.post<PrivacyRequestResponse>(
        PRIVACY_ERASURE_ENDPOINT,
        {
          user_id: scopedUserId,
          tenant_id: tenantId.trim() || null,
          erasure_type: erasureType.trim() || DEFAULT_ERASURE_TYPE,
          data_types: parsedDataTypes,
          confirmation_token: token,
        },
      );

      setLastRequest(response);
      setRequestId(response.request_id);
      setVerificationToken(response.verification_token);
      setShowVerificationToken(false);

      toast({
        title: 'Erasure request created',
        description: `Privacy request ${response.request_id} is awaiting verification and processing.`,
      });
    } catch (error) {
      handleRequestError(
        error,
        'erasure',
        'Erasure request failed',
        'Karen could not submit the privacy erasure request.',
      );
    } finally {
      setIsSubmittingErasure(false);
    }
  }, [
    confirmationToken,
    erasureType,
    handleRequestError,
    parsedDataTypes,
    setActionAccessDenied,
    tenantId,
    toast,
    userId,
  ]);

  const handleLookupStatus = useCallback(async () => {
    const scopedRequestId = normalizeRequestId(requestId);

    if (!scopedRequestId) {
      return;
    }

    setIsLoadingStatus(true);
    setRequestStatus(null);
    setAuthRequired(false);
    setActionAccessDenied('status', false);

    try {
      const response = await apiClient.get<PrivacyRequestStatusResponse>(
        `/api/privacy/request/${encodeURIComponent(scopedRequestId)}/status`,
      );
      setRequestStatus(response);
    } catch (error) {
      handleRequestError(
        error,
        'status',
        'Status lookup failed',
        'Karen could not retrieve the privacy request status.',
      );
    } finally {
      setIsLoadingStatus(false);
    }
  }, [handleRequestError, requestId, setActionAccessDenied]);

  const handleProcessRequest = useCallback(async () => {
    const scopedRequestId = normalizeRequestId(requestId);
    const scopedVerificationToken = verificationToken.trim();

    if (!scopedRequestId || !scopedVerificationToken) {
      return;
    }

    setIsProcessingRequest(true);
    setAuthRequired(false);
    setActionAccessDenied('process', false);

    try {
      await apiClient.post(
        `/api/privacy/request/${encodeURIComponent(
          scopedRequestId,
        )}/process?verification_token=${encodeURIComponent(
          scopedVerificationToken,
        )}`,
        {},
      );

      toast({
        title: 'Privacy request processed',
        description: `Karen submitted ${scopedRequestId} for backend privacy processing.`,
      });

      const response = await apiClient.get<PrivacyRequestStatusResponse>(
        `/api/privacy/request/${encodeURIComponent(scopedRequestId)}/status`,
      );
      setRequestStatus(response);
    } catch (error) {
      handleRequestError(
        error,
        'process',
        'Privacy processing failed',
        'Karen could not process the privacy request.',
      );
    } finally {
      setIsProcessingRequest(false);
    }
  }, [handleRequestError, requestId, setActionAccessDenied, toast, verificationToken]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Privacy & Data Control</CardTitle>
        <CardDescription>
          Review local browser storage, check privacy service health, and submit
          governed export or erasure requests through Karen&apos;s backend.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {authRequired && (
          <Alert className="border-primary/20 bg-primary/5">
            <ShieldAlert className="h-4 w-4 !text-primary" aria-hidden="true" />
            <AlertTitle>Sign In Required</AlertTitle>
            <AlertDescription>
              Karen&apos;s privacy workflows are live, but this session is not
              authenticated. Sign in before requesting export, erasure, or request
              processing.
            </AlertDescription>
          </Alert>
        )}

        {accessDenied.health && (
          <Alert className="border-primary/20 bg-primary/5">
            <ShieldAlert className="h-4 w-4 !text-primary" aria-hidden="true" />
            <AlertTitle>Privacy Health Restricted</AlertTitle>
            <AlertDescription>
              Backend RBAC prevented this session from reading privacy service health.
            </AlertDescription>
          </Alert>
        )}

        <Alert variant="default" className="border-border bg-background">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle className="text-sm font-semibold">
            Backend-Governed Privacy
          </AlertTitle>
          <AlertDescription className="space-y-1 text-xs text-muted-foreground">
            <p>
              Privacy export and erasure workflows are live backend operations.
              The UI submits requests only; backend RBAC, audit, verification,
              tenant checks, and processing decide the outcome.
            </p>
            <ul className="list-inside list-disc pl-4">
              <li>
                <strong>Local browser storage:</strong> convenience-only UI state.
              </li>
              <li>
                <strong>Backend privacy controls:</strong> export requests,
                erasure requests, audit-backed processing, and request status.
              </li>
            </ul>
          </AlertDescription>
        </Alert>

        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldCheck className="h-5 w-5 text-primary" aria-hidden="true" />
                Privacy Service Status
              </CardTitle>
              <CardDescription>
                Backend-derived privacy capabilities for export, erasure, and
                content sanitization.
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-4">
              {isLoadingHealth ? (
                <div
                  className="flex items-center gap-2 rounded-xl border border-border/70 p-4 text-sm text-muted-foreground"
                  role="status"
                  aria-live="polite"
                >
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  Loading privacy service status.
                </div>
              ) : health ? (
                <>
                  <div className="flex items-center justify-between rounded-xl border border-border/70 p-4">
                    <div>
                      <div className="font-medium">Service</div>
                      <div className="text-sm text-muted-foreground">
                        {health.service}
                      </div>
                    </div>
                    <div className="text-sm font-medium">{health.status}</div>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    {privacyServiceFeatures.map(([feature, enabled]) => (
                      <div
                        key={feature}
                        className="rounded-xl border border-border/70 p-4 text-sm"
                      >
                        <div className="font-medium">
                          {feature.replace(/_/g, ' ')}
                        </div>
                        <div className="mt-1 text-muted-foreground">
                          {enabled ? 'Enabled' : 'Disabled'}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <Alert className="border-yellow-500/30 bg-yellow-500/5">
                  <Info className="h-4 w-4 !text-yellow-600" aria-hidden="true" />
                  <AlertTitle>Privacy Service Unavailable</AlertTitle>
                  <AlertDescription>
                    {healthError ||
                      'Karen could not confirm the privacy backend state.'}
                  </AlertDescription>
                </Alert>
              )}

              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void loadHealth()}
                disabled={isLoadingHealth}
              >
                {isLoadingHealth ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <ShieldCheck className="mr-2 h-4 w-4" aria-hidden="true" />
                )}
                Refresh Privacy Health
              </Button>
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Info className="h-5 w-5 text-primary" aria-hidden="true" />
                Request Context
              </CardTitle>
              <CardDescription>
                Scope the privacy request to the authenticated user and tenant.
                Backend RBAC still verifies every request.
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-4">
              <div className="grid gap-2">
                <Label htmlFor="privacy-user-id">User ID</Label>
                <Input
                  id="privacy-user-id"
                  value={userId}
                  onChange={(event) => setUserId(event.target.value)}
                  placeholder="user_123"
                  disabled={Boolean(user?.user_id)}
                />
                {user?.user_id && (
                  <p className="text-xs text-muted-foreground">
                    Filled from authenticated session.
                  </p>
                )}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="privacy-tenant-id">Tenant ID</Label>
                <Input
                  id="privacy-tenant-id"
                  value={tenantId}
                  onChange={(event) => setTenantId(event.target.value)}
                  placeholder="tenant_abc"
                  disabled={Boolean(user?.tenant_id)}
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="privacy-data-types">Data types</Label>
                <Input
                  id="privacy-data-types"
                  value={dataTypes}
                  onChange={(event) => setDataTypes(event.target.value)}
                  placeholder="all or memories,conversations,audit_logs"
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="privacy-export-format">Export format</Label>
                <Input
                  id="privacy-export-format"
                  value={exportFormat}
                  onChange={(event) => setExportFormat(event.target.value)}
                  placeholder="json"
                />
              </div>
            </CardContent>
          </Card>
        </div>

        <Separator />

        <div className="grid gap-6 xl:grid-cols-2">
          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <FileDown className="h-5 w-5 text-primary" aria-hidden="true" />
                Data Export Request
              </CardTitle>
              <CardDescription>
                Create a governed backend export request.
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-4">
              {accessDenied.export && (
                <Alert className="border-primary/20 bg-primary/5">
                  <ShieldAlert className="h-4 w-4 !text-primary" aria-hidden="true" />
                  <AlertTitle>Export Access Restricted</AlertTitle>
                  <AlertDescription>
                    This session does not have permission to create privacy export
                    requests.
                  </AlertDescription>
                </Alert>
              )}

              <Button
                type="button"
                onClick={() => void handleRequestExport()}
                disabled={isSubmittingExport || !canSubmitScopedRequest}
              >
                {isSubmittingExport ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <FileDown className="mr-2 h-4 w-4" aria-hidden="true" />
                )}
                Request Data Export
              </Button>
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Trash2 className="h-5 w-5 text-primary" aria-hidden="true" />
                Data Erasure Request
              </CardTitle>
              <CardDescription>
                Submit backend erasure requests with explicit erasure mode and
                confirmation token.
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-4">
              {accessDenied.erasure && (
                <Alert className="border-primary/20 bg-primary/5">
                  <ShieldAlert className="h-4 w-4 !text-primary" aria-hidden="true" />
                  <AlertTitle>Erasure Access Restricted</AlertTitle>
                  <AlertDescription>
                    This session does not have permission to create privacy erasure
                    requests.
                  </AlertDescription>
                </Alert>
              )}

              <div className="grid gap-2">
                <Label htmlFor="erasure-type">Erasure type</Label>
                <Input
                  id="erasure-type"
                  value={erasureType}
                  onChange={(event) => setErasureType(event.target.value)}
                  placeholder="soft_delete"
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="confirmation-token">Confirmation token</Label>
                <Input
                  id="confirmation-token"
                  value={confirmationToken}
                  onChange={(event) => setConfirmationToken(event.target.value)}
                  placeholder="required for erasure requests"
                />
              </div>

              <Button
                type="button"
                variant="outline"
                onClick={() => void handleRequestErasure()}
                disabled={
                  isSubmittingErasure ||
                  !canSubmitScopedRequest ||
                  !confirmationToken.trim()
                }
              >
                {isSubmittingErasure ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <FileWarning className="mr-2 h-4 w-4" aria-hidden="true" />
                )}
                Request Data Erasure
              </Button>
            </CardContent>
          </Card>
        </div>

        {lastRequest && (
          <Card className="border-border/70 bg-muted/20">
            <CardHeader>
              <CardTitle className="text-base">Latest Privacy Request</CardTitle>
              <CardDescription>
                Backend-issued identifiers and verification data for the most recent
                request.
              </CardDescription>
            </CardHeader>

            <CardContent className="grid gap-2 text-sm">
              <div>
                <strong>Request ID:</strong> {lastRequest.request_id}
              </div>
              <div>
                <strong>Status:</strong> {lastRequest.status}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <strong>Verification token:</strong>
                <span className="font-mono">
                  {showVerificationToken
                    ? lastRequest.verification_token
                    : '••••••••••••'}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setShowVerificationToken((current) => !current)
                  }
                  className="h-7 px-2"
                >
                  {showVerificationToken ? (
                    <EyeOff className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                  ) : (
                    <Eye className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {showVerificationToken ? 'Hide' : 'Reveal'}
                </Button>
              </div>
              <div>
                <strong>ETA:</strong> {lastRequest.estimated_completion}
              </div>
              <div className="text-muted-foreground">{lastRequest.next_steps}</div>
            </CardContent>
          </Card>
        )}

        <Separator />

        <Card className="border-border/70">
          <CardHeader>
            <CardTitle className="text-base">Request Status & Processing</CardTitle>
            <CardDescription>
              Inspect or process an existing privacy request through the live backend
              privacy routes.
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-4">
            {(accessDenied.status || accessDenied.process) && (
              <Alert className="border-primary/20 bg-primary/5">
                <ShieldAlert className="h-4 w-4 !text-primary" aria-hidden="true" />
                <AlertTitle>Privacy Workflow Restricted</AlertTitle>
                <AlertDescription>
                  This session can see the panel, but backend RBAC is restricting
                  privacy request inspection or processing.
                </AlertDescription>
              </Alert>
            )}

            <div className="grid gap-4 md:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="privacy-request-id">Request ID</Label>
                <Input
                  id="privacy-request-id"
                  value={requestId}
                  onChange={(event) => setRequestId(event.target.value)}
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="privacy-verification-token">
                  Verification token
                </Label>
                <Input
                  id="privacy-verification-token"
                  value={verificationToken}
                  onChange={(event) => setVerificationToken(event.target.value)}
                  type={showVerificationToken ? 'text' : 'password'}
                />
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <Button
                type="button"
                variant="outline"
                onClick={() => void handleLookupStatus()}
                disabled={isLoadingStatus || !requestId.trim()}
              >
                {isLoadingStatus ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Info className="mr-2 h-4 w-4" aria-hidden="true" />
                )}
                Check Request Status
              </Button>

              <Button
                type="button"
                onClick={() => void handleProcessRequest()}
                disabled={
                  isProcessingRequest ||
                  !requestId.trim() ||
                  !verificationToken.trim()
                }
              >
                {isProcessingRequest ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <ShieldCheck className="mr-2 h-4 w-4" aria-hidden="true" />
                )}
                Process Verified Request
              </Button>
            </div>

            {requestStatus && (
              <div className="rounded-xl border border-border/70 p-4 text-sm">
                <div>
                  <strong>Status:</strong> {requestStatus.status}
                </div>
                <div>
                  <strong>Created:</strong>{' '}
                  {getSafeDateTimeLabel(requestStatus.created_at)}
                </div>
                <div>
                  <strong>Completed:</strong>{' '}
                  {requestStatus.completed_at
                    ? getSafeDateTimeLabel(requestStatus.completed_at)
                    : 'Pending'}
                </div>
                <pre className="mt-3 whitespace-pre-wrap break-words rounded-md bg-muted/40 p-3 text-xs">
                  {JSON.stringify(requestStatus.progress, null, 2)}
                </pre>
              </div>
            )}
          </CardContent>
        </Card>
      </CardContent>
    </Card>
  );
}
