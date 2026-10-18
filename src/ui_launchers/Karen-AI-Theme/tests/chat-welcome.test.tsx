import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MessagesArea } from '@/components/chat/interface/MessagesArea';

vi.mock('@/components/ui/scroll-area', () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('@/components/chat/MessageBubble', () => ({
  MessageBubble: ({ message }: { message: { content: string } }) => <div>{message.content}</div>,
}));

const refs = {
  viewportRef: { current: null },
  messagesContainerRef: { current: null },
};

describe('chat first-use welcome', () => {
  it('explains capabilities and fills a draft without sending', () => {
    const onPromptSelect = vi.fn();
    render(
      <MessagesArea
        messages={[]}
        onActionClick={vi.fn()}
        showWelcome
        onPromptSelect={onPromptSelect}
        {...refs}
      />,
    );

    expect(screen.getByRole('heading', { name: 'What can Karen help you accomplish?' })).toBeTruthy();
    expect(screen.getByText(/Nothing is sent until you choose Send/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Make a plan' }));
    expect(onPromptSelect).toHaveBeenCalledOnce();
    expect(onPromptSelect).toHaveBeenCalledWith(
      'Help me make a practical plan for a project I want to start.',
    );
  });

  it('does not show examples while an existing conversation is displayed', () => {
    render(
      <MessagesArea
        messages={[{
          id: 'user-1',
          role: 'user',
          content: 'A real message',
          timestamp: new Date(),
        }]}
        onActionClick={vi.fn()}
        showWelcome
        onPromptSelect={vi.fn()}
        {...refs}
      />,
    );
    expect(screen.queryByTestId('chat-welcome')).toBeNull();
    expect(screen.getByText('A real message')).toBeTruthy();
  });

  it('does not show an empty-session welcome during loading', () => {
    render(
      <MessagesArea
        messages={[]}
        onActionClick={vi.fn()}
        showWelcome={false}
        onPromptSelect={vi.fn()}
        {...refs}
      />,
    );
    expect(screen.queryByTestId('chat-welcome')).toBeNull();
  });
});
