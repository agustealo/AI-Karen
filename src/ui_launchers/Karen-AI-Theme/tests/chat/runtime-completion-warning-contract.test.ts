import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('Chat completion truth presentation', () => {
  const verifiedHistory = readFileSync(
    resolve(process.cwd(), 'src/components/chat/copilotkit/KarenCopilotVerifiedHistory.tsx'),
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
    expect(verifiedHistory).toContain('KarenResponseIntegrity');
    expect(verifiedHistory).toContain('@/components/chat/KarenVerifiedReceipts');
    expect(sharedReceiptSource).toContain('receipt.output_truncated === true');
    expect(sharedReceiptSource).toContain('This answer stopped at the model&apos;s output-token limit');
  });

  it('exposes an accessible incomplete-answer status', () => {
    expect(verifiedHistory).toContain('KarenResponseIntegrity');
    expect(sharedReceiptSource).toContain('role="status" aria-live="polite"');
    expect(sharedReceiptSource).toContain('data-testid="karen-output-truncated"');
  });
});
