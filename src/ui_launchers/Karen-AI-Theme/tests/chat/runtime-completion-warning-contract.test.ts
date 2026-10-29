import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('Chat completion truth presentation', () => {
  const chatSource = readFileSync(
    resolve(process.cwd(), 'src/components/chat/assistant-ui/KarenAssistantChat.tsx'),
    'utf8',
  );
  const sharedReceiptSource = readFileSync(
    resolve(process.cwd(), 'src/components/chat/KarenVerifiedReceipts.tsx'),
    'utf8',
  );
  const projectionSource = readFileSync(
    resolve(process.cwd(), '../../ai_karen_engine/core/runtime/ag_ui_event_projection.py'),
    'utf8',
  );

  it('uses explicit backend truncation truth rather than inspecting punctuation', () => {
    expect(projectionSource).toContain('meta.get("output_truncated") is True');
    expect(chatSource).toContain('KarenResponseIntegrity');
    expect(chatSource).toContain('../KarenVerifiedReceipts');
    expect(sharedReceiptSource).toContain('receipt.output_truncated === true');
    expect(sharedReceiptSource).toContain('This answer stopped at the model&apos;s output-token limit');
  });

  it('exposes an accessible incomplete-answer status', () => {
    expect(chatSource).toContain('KarenResponseIntegrity');
    expect(sharedReceiptSource).toContain('role="status" aria-live="polite"');
    expect(sharedReceiptSource).toContain('data-testid="karen-output-truncated"');
  });
});
