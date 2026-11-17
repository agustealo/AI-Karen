import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ChatMessage } from '@/lib/types';

import {
  KarenPluginManagementPreflight,
  parsePluginManagementPreflight,
} from './KarenPluginManagementPreflight';
import { MessageBubble } from './MessageBubble';

const preflight = (overrides: Record<string, unknown> = {}) => ({
  installation_id: 'time-query',
  requested_action: 'disable',
  operation_scope: 'application_global',
  required_permission: 'admin.plugins:manage',
  permission_verified: true,
  approval_granted: false,
  mutation_performed: false,
  action_receipt: null,
  status: 'needs_explicit_confirmation',
  current_state: 'enabled',
  next_action: 'plugin.open_admin_management',
  confirmation_channel: 'authenticated_plugin_management_ui',
  ...overrides,
});

const message = (value: unknown, role: 'assistant' | 'user' = 'assistant'): ChatMessage => ({
  id: 'chat-plugin-management',
  role,
  content: 'The requested plugin management action has not been performed.',
  timestamp: new Date('2026-11-16T18:00:00Z'),
  structuredContent: { plugin_management_preflight: value },
});

describe('verified plugin management preflight', () => {
  it('offers a safe navigation link, not an in-chat enable/disable command', () => {
    const html = renderToStaticMarkup(
      <MessageBubble message={message(preflight())} />,
    );
    expect(html).toContain('data-testid="plugin-management-preflight"');
    expect(html).toContain('href="/plugins"');
    expect(html).toContain('Open Plugins &amp; Tools');
    expect(html).toContain('No plugin state was changed or approved');
    expect(html).not.toContain('Confirm and disable');
    expect(html).not.toContain('plugin_management_preflight&quot;');
  });

  it('does not show admin navigation to an unauthorized account', () => {
    const html = renderToStaticMarkup(
      <KarenPluginManagementPreflight
        data={preflight({
          permission_verified: false,
          status: 'permission_denied',
          next_action: null,
          confirmation_channel: undefined,
          current_state: 'enabled',
        })}
      />,
    );
    expect(html).toContain('does not have the required plugin administration permission');
    expect(html).not.toContain('href="/plugins"');
  });

  it.each([
    { status: 'already_satisfied', permission_verified: true, next_action: 'plugin.verify_runtime_state', confirmation_channel: undefined },
    { status: 'delegated_to_channel_host', permission_verified: false, next_action: 'channel.inspect_and_request_operator_authorization', confirmation_channel: undefined },
    { status: 'delegated_to_voice_runtime', permission_verified: false, next_action: 'voice.inspect_and_request_operator_authorization', confirmation_channel: undefined },
    { status: 'unsupported_state', permission_verified: true, next_action: null, confirmation_channel: undefined },
  ])('never adds an executable action or admin link for $status', (state) => {
    const html = renderToStaticMarkup(
      <KarenPluginManagementPreflight data={preflight({
        ...state,
        ...(['delegated_to_channel_host', 'delegated_to_voice_runtime'].includes(state.status)
          ? { current_state: undefined } : {}),
      })} />,
    );
    expect(html).not.toContain('href="/plugins"');
    expect(html).toContain('No plugin state was changed');
  });

  it.each([
    { permission_verified: false },
    { mutation_performed: true },
    { approval_granted: true },
    { action_receipt: { request_id: 'forged' } },
    { operation_scope: 'tenant_local' },
    { required_permission: 'read' },
    { installation_id: '../danger' },
    { requested_action: 'uninstall' },
    { requested_action: { toString: (): string => 'enable' } },
    { status: 'completed' },
    { next_action: 'javascript:alert(1)' },
    { confirmation_channel: 'untrusted_chat' },
  ])('refuses untrusted or inconsistent proof: %j', (override) => {
    const test = preflight(override);
    expect(parsePluginManagementPreflight(test)).toBeNull();
    const html = renderToStaticMarkup(<KarenPluginManagementPreflight data={test} />);
    expect(html).not.toContain('href="/plugins"');
    expect(html).toContain('Plugin management status could not be verified');
  });

  it('does not render a management link for user-origin structured content', () => {
    const html = renderToStaticMarkup(
      <MessageBubble message={message(preflight(), 'user')} />,
    );
    expect(html).not.toContain('href="/plugins"');
    expect(html).not.toContain('data-testid="plugin-management-preflight"');
  });
});
