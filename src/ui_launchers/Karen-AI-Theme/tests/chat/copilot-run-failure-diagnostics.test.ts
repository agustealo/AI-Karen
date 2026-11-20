import { describe, expect, it } from 'vitest';
import { getCopilotRunFailureMessage } from '@/components/chat/const/getDegradedResponseMessage';

describe('KCHAT safe CopilotKit runtime error diagnostics', () => {
  it('maps only known backend AG-UI error codes to actionable guidance', () => {
    expect(getCopilotRunFailureMessage({
      event: { code: 'CHAT_SSE_MISSING_TERMINAL' },
    })).toContain('incomplete response stream');
    expect(getCopilotRunFailureMessage({
      error: { code: 'CHAT_TRANSCRIPT_PERSISTENCE_FAILED' },
    })).toContain('could not be verified as saved');
    expect(getCopilotRunFailureMessage({
      code: 'BACKEND_TARGET_NOT_CONFIGURED',
    })).toContain('administrator');
  });

  it('does not leak provider keys, raw exception text or arbitrary error codes', () => {
    const failure = {
      code: 'PRIVATE_PROVIDER_SECRET',
      message: 'password=hunter2 https://private-internal-model',
      cause: { message: 'secret=123' },
    };
    const result = getCopilotRunFailureMessage(failure);
    expect(result).toContain('did not provide a recognized failure code');
    expect(result).not.toContain('hunter2');
    expect(result).not.toContain('PRIVATE_PROVIDER_SECRET');
    expect(result).not.toContain('private-internal-model');
    expect(result).not.toContain('secret=123');
  });

  it('identifies HTTP authentication and availability statuses without raw messages', () => {
    expect(getCopilotRunFailureMessage({ status: 401, message: 'private auth token' }))
      .toContain('Sign in again');
    expect(getCopilotRunFailureMessage({ response: { status: 503 } }))
      .toContain('required dependency is unavailable');
    expect(getCopilotRunFailureMessage({ status: 429 }))
      .toContain('rate-limited');
    expect(getCopilotRunFailureMessage(new Error('Unable to complete the response.')))
      .toContain('verified conversation history');
  });

  it('does not claim the user message was never saved after a terminal failure', () => {
    for (const failure of [
      undefined, null, 'private upstream failed', { code: 'CHAT_STREAM_UPSTREAM_INTERRUPTED' },
    ]) {
      const result = getCopilotRunFailureMessage(failure);
      expect(result).toMatch(/history/i);
      expect(result).not.toContain('No message was sent');
      expect(result).not.toContain('not saved');
    }
  });
});
