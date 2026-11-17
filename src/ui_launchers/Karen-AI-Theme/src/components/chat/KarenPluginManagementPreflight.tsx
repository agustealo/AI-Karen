import Link from 'next/link';

type ManagementStatus =
  | 'needs_explicit_confirmation'
  | 'already_satisfied'
  | 'permission_denied'
  | 'unavailable_installation'
  | 'unsupported_state'
  | 'delegated_to_channel_host'
  | 'delegated_to_voice_runtime';

interface ManagementPreflight {
  installationId: string;
  action: 'enable' | 'disable';
  status: ManagementStatus;
  permissionVerified: boolean;
  nextAction: string | null;
  confirmationChannel: string | null;
}

const STATUSES: ReadonlySet<string> = new Set<ManagementStatus>([
  'needs_explicit_confirmation',
  'already_satisfied',
  'permission_denied',
  'unavailable_installation',
  'unsupported_state',
  'delegated_to_channel_host',
  'delegated_to_voice_runtime',
]);

const NEXT_ACTION: Record<ManagementStatus, string | null> = {
  needs_explicit_confirmation: 'plugin.open_admin_management',
  already_satisfied: 'plugin.verify_runtime_state',
  permission_denied: null,
  unavailable_installation: null,
  unsupported_state: null,
  delegated_to_channel_host: 'channel.inspect_and_request_operator_authorization',
  delegated_to_voice_runtime: 'voice.inspect_and_request_operator_authorization',
};
const PREFLIGHT_FIELDS = new Set([
  'installation_id', 'requested_action', 'operation_scope',
  'required_permission', 'permission_verified', 'approval_granted',
  'mutation_performed', 'action_receipt', 'next_action', 'status',
  'current_state', 'confirmation_channel',
]);

/**
 * Parse only the canonical backend's non-executable preflight envelope.
 * Never infer permission or treat an approval suggestion as an action token.
 */
export function parsePluginManagementPreflight(data: unknown): ManagementPreflight | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return null;
  }
  const record = data as Record<string, unknown>;
  if (
    typeof record.installation_id !== 'string' ||
    !/^[a-z][a-z0-9_-]{0,49}$/.test(record.installation_id) ||
    typeof record.requested_action !== 'string' ||
    !['enable', 'disable'].includes(record.requested_action) ||
    typeof record.status !== 'string' ||
    !STATUSES.has(record.status) ||
    record.operation_scope !== 'application_global' ||
    record.required_permission !== 'admin.plugins:manage' ||
    typeof record.permission_verified !== 'boolean' ||
    record.mutation_performed !== false ||
    record.approval_granted !== false ||
    record.action_receipt !== null ||
    (record.next_action !== null && typeof record.next_action !== 'string') ||
    (record.confirmation_channel != null && typeof record.confirmation_channel !== 'string') ||
    Object.keys(record).some((key) => !PREFLIGHT_FIELDS.has(key))
  ) {
    return null;
  }
  const status = record.status as ManagementStatus;
  const stateRequired = [
    'needs_explicit_confirmation', 'already_satisfied',
    'permission_denied', 'unsupported_state',
  ].includes(status);
  const currentState = record.current_state;
  const expectedPermission = [
    'needs_explicit_confirmation', 'already_satisfied', 'unsupported_state',
  ].includes(status);
  if (
    record.next_action !== NEXT_ACTION[status] ||
    record.permission_verified !== expectedPermission ||
    (currentState != null) !== stateRequired ||
    (currentState != null &&
      (typeof currentState !== 'string' || !/^[a-z][a-z_]{1,31}$/.test(currentState))) ||
    (status === 'needs_explicit_confirmation'
      ? record.confirmation_channel !== 'authenticated_plugin_management_ui'
      : record.confirmation_channel != null)
  ) {
    return null;
  }

  return {
    installationId: record.installation_id,
    action: record.requested_action as 'enable' | 'disable',
    status: record.status as ManagementStatus,
    permissionVerified: record.permission_verified,
    nextAction: record.next_action,
    confirmationChannel: typeof record.confirmation_channel === 'string'
      ? record.confirmation_channel : null,
  };
}

export function KarenPluginManagementPreflight({ data }: { data: unknown }) {
  const preflight = parsePluginManagementPreflight(data);
  if (!preflight) {
    return (
      <p data-testid="plugin-management-invalid" className="text-sm text-muted-foreground">
        Plugin management status could not be verified. No action was performed.
      </p>
    );
  }

  const canNavigateToManagement =
    preflight.status === 'needs_explicit_confirmation' &&
    preflight.permissionVerified &&
    preflight.nextAction === 'plugin.open_admin_management' &&
    preflight.confirmationChannel === 'authenticated_plugin_management_ui';

  const detail =
    preflight.status === 'needs_explicit_confirmation'
      ? 'This action requires a separate authenticated administrator confirmation.'
      : preflight.status === 'already_satisfied'
        ? 'The recorded plugin state already satisfies the requested action. Runtime health is not verified.'
        : preflight.status === 'permission_denied'
          ? 'Your account does not have the required plugin administration permission.'
          : preflight.status === 'delegated_to_channel_host'
            ? 'This communication plugin is governed by the ChannelHost, not global generic management.'
            : preflight.status === 'delegated_to_voice_runtime'
              ? 'This voice plugin is governed by VoiceRuntime, not global generic management.'
              : 'The requested action cannot be completed through this management workflow.';

  return (
    <section
      aria-label="Plugin management preflight"
      data-testid="plugin-management-preflight"
      className="space-y-2 text-sm"
    >
      <p className="font-medium text-foreground">
        {preflight.installationId}: {preflight.action}
      </p>
      <p className="text-muted-foreground">{detail}</p>
      <p className="text-xs text-muted-foreground">
        No plugin state was changed or approved by this conversation.
      </p>
      {canNavigateToManagement && (
        <Link
          href="/plugins"
          className="inline-flex rounded-md border border-border px-3 py-2 text-sm font-medium text-primary hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          Open Plugins &amp; Tools
        </Link>
      )}
    </section>
  );
}
