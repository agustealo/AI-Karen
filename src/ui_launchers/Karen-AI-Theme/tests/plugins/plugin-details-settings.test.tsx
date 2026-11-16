import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import { PluginDetailsModal } from '@/components/plugins/PluginDetailsModal';

vi.mock('@/plugin_host/plugin-settings', () => ({
  PluginSettingsProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PluginSettingsForm: ({ pluginId }: { pluginId: string }) => (
    <span>Governed settings for {pluginId}</span>
  ),
}));

const plugin = {
  id: 'settings-test',
  name: 'settings-test',
  display_name: 'Settings Test',
  description: 'Known plugin settings',
  author: 'Tests',
  version: '1.0.0',
  status: 'installed' as const,
  runtime_status: 'enabled',
};

afterEach(cleanup);

describe('Plugin details settings affordance', () => {
  it('mounts existing settings form only when backend reports a settings schema', () => {
    render(
      <PluginDetailsModal
        open
        onOpenChange={vi.fn()}
        details={{
          installed: true,
          plugin: { ...plugin, settings_available: true },
        }}
      />,
    );

    const button = screen.getByRole('button', { name: 'Configure' });
    fireEvent.click(button);
    expect(screen.getByText('Governed settings for settings-test')).toBeTruthy();
    expect(button.getAttribute('aria-expanded')).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: 'Hide settings' }));
    expect(screen.queryByText('Governed settings for settings-test')).toBeNull();
  });

  it('opens the host Voice Studio for a confirmed TTS plugin even without a plugin settings schema', () => {
    const openVoiceStudio = vi.fn();
    render(
      <PluginDetailsModal
        open
        onOpenChange={vi.fn()}
        onOpenVoiceStudio={openVoiceStudio}
        details={{
          installed: true,
          plugin: { ...plugin, id: 'pocket-tts', display_name: 'Pocket TTS', settings_available: false },
        }}
      />,
    );

    expect(screen.queryByRole('button', { name: 'Configure' })).toBeNull();
    const openButton = screen.getByRole('button', { name: 'Open Voice Studio for Pocket TTS' });
    fireEvent.click(openButton);
    expect(openVoiceStudio).toHaveBeenCalledOnce();
  });

  it('does not claim a Voice Studio action for a plugin without backend TTS evidence', () => {
    render(
      <PluginDetailsModal
        open
        onOpenChange={vi.fn()}
        details={{
          installed: true,
          plugin: { ...plugin, id: 'not-tts', settings_available: false },
        }}
      />,
    );
    expect(screen.queryByRole('button', { name: /Open Voice Studio/ })).toBeNull();
  });

  it('does not invent a settings form when backend reports no schema', () => {
    render(
      <PluginDetailsModal
        open
        onOpenChange={vi.fn()}
        details={{
          installed: true,
          plugin: { ...plugin, settings_available: false },
        }}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Configure' })).toBeNull();
  });
});
