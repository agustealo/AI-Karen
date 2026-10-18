import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('Chat completion truth presentation', () => {
  const chatSource = readFileSync(
    resolve(process.cwd(), 'src/components/chat/ChatInterface.tsx'),
    'utf8',
  );

  it('uses explicit backend truncation truth rather than inspecting punctuation', () => {
    expect(chatSource).toContain('metadata.output_truncated === true');
    expect(chatSource).toContain('latestAssistantMetadata.outputTruncated &&');
    expect(chatSource.replaceAll('&apos;', "'")).toContain("This answer stopped at the model's output-token limit");
  });

  it('exposes an accessible incomplete-answer status', () => {
    expect(chatSource).toContain('role="status" aria-live="polite"');
  });
});
