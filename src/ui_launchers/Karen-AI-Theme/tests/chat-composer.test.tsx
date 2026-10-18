import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatInput } from '@/components/chat/interface/ChatInput';

vi.mock('@/components/chat/const/ProviderSettingsModal', () => ({
  ProviderSettingsModal: () => null,
}));
vi.mock('@/components/chat/const/SessionHistory', () => ({
  SessionHistory: () => null,
}));
vi.mock('@/components/chat/const/ChatActionsMenu', () => ({
  ChatActionsMenu: () => null,
}));

function renderComposer(overrides: Partial<React.ComponentProps<typeof ChatInput>> = {}) {
  const onSubmit = vi.fn((event: React.FormEvent<HTMLFormElement>) => event.preventDefault());
  const onInputChange = vi.fn();
  const onStopRequest = vi.fn();
  render(
    <ChatInput
      onSubmit={onSubmit}
      displayedInputValue="Hello Karen"
      onInputChange={onInputChange}
      isLoading={false}
      isAuthLoading={false}
      isRecording={false}
      isBackendOffline={false}
      speechRecognitionSupported={false}
      showStopButton={false}
      streamingStatus=""
      onMicClick={vi.fn()}
      onStopRequest={onStopRequest}
      providers={[]}
      selectableProviders={[]}
      selectedProvider="local"
      selectedModel="active-model"
      applyModelSelection={vi.fn(async () => undefined)}
      isUpdatingModelSelection={false}
      onRefreshModels={vi.fn(async () => undefined)}
      sessions={[]}
      currentSession={null}
      isLoadingSessions={false}
      error={null}
      loadSession={vi.fn(async () => undefined)}
      deleteSession={vi.fn(async () => true)}
      deleteSessions={vi.fn(async () => true)}
      updateSessionTitle={vi.fn(async () => true)}
      refreshSessions={vi.fn(async () => undefined)}
      createNewSession={vi.fn(async () => undefined)}
      onExportChat={vi.fn()}
      {...overrides}
    />,
  );
  return { onSubmit, onInputChange, onStopRequest };
}

afterEach(() => vi.restoreAllMocks());

describe('Karen multiline composer', () => {
  it('preserves the next-message draft while a response streams', () => {
    const { onInputChange } = renderComposer({
      displayedInputValue: 'Draft for the next message',
      isLoading: true,
      showStopButton: true,
      streamingStatus: 'Generating response',
    });
    const input = screen.getByRole('textbox', { name: 'Chat message input' }) as HTMLTextAreaElement;
    expect(input.value).toBe('Draft for the next message');
    expect(screen.getByRole('status').textContent).toContain('Generating response');
    fireEvent.change(input, { target: { value: 'Another draft' } });
    expect(onInputChange).toHaveBeenCalledWith('Another draft');
  });

  it('does not substitute processing status for an empty user draft', () => {
    renderComposer({
      displayedInputValue: '',
      isLoading: true,
      showStopButton: true,
      streamingStatus: 'Searching for context',
    });
    const input = screen.getByRole('textbox', { name: 'Chat message input' }) as HTMLTextAreaElement;
    expect(input.value).toBe('');
    expect(input.placeholder).toBe('Ask Karen anything...');
    expect(screen.getByRole('status').textContent).toContain('Searching for context');
  });

  it('retains an existing next-message draft after Stop', () => {
    const { onStopRequest } = renderComposer({
      displayedInputValue: 'Important unsent draft',
      isLoading: true,
      showStopButton: true,
      streamingStatus: 'Generating response',
    });
    const input = screen.getByRole('textbox', { name: 'Chat message input' }) as HTMLTextAreaElement;
    fireEvent.click(screen.getByRole('button', { name: 'Stop current response generation' }));
    expect(onStopRequest).toHaveBeenCalledOnce();
    expect(input.value).toBe('Important unsent draft');
  });

  it('renders a multiline textbox with matching keyboard guidance', () => {
    renderComposer();
    const input = screen.getByRole('textbox', { name: 'Chat message input' });
    expect(input.tagName).toBe('TEXTAREA');
    expect(input.getAttribute('aria-multiline')).toBe('true');
    expect(document.getElementById('input-help')?.textContent).toContain('Shift+Enter');
  });

  it('sends on Enter and does not send on Shift+Enter', () => {
    const { onSubmit } = renderComposer();
    const input = screen.getByRole('textbox', { name: 'Chat message input' });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('does not send modified Enter or IME composition', () => {
    const { onSubmit } = renderComposer();
    const input = screen.getByRole('textbox', { name: 'Chat message input' });
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
    fireEvent.keyDown(input, { key: 'Enter', metaKey: true });
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('does not start another request while generation is active', () => {
    const { onSubmit, onStopRequest } = renderComposer({
      isLoading: true,
      showStopButton: true,
    });
    const input = screen.getByRole('textbox', { name: 'Chat message input' });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Stop current response generation' }));
    expect(onStopRequest).toHaveBeenCalledOnce();
  });
});
