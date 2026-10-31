import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('conversation rail sidebar typography', () => {
  it('uses the conversation sidebar scale for card headings and explanatory empty states', () => {
    const rail = readFileSync(resolve(process.cwd(), 'src/components/chat/ConversationContextRail.tsx'), 'utf8');
    const chat = readFileSync(resolve(process.cwd(), 'src/components/chat/copilotkit/KarenCopilotConsumerChat.tsx'), 'utf8');
    const titles = [...rail.matchAll(/<CardTitle className="([^"]+)"/g)].map((match) => match[1]);
    expect(titles.length).toBeGreaterThan(0);
    expect(titles.every((classes) => classes.includes('text-sm font-medium'))).toBe(true);
    expect(titles.every((classes) => !classes.includes('uppercase') && !classes.includes('text-xs'))).toBe(true);
    expect(rail).toContain('<p className="text-sm leading-relaxed text-muted-foreground">{children}</p>');
    expect(chat).toContain('px-3 py-2 text-left text-sm hover:bg-muted');
  });
});
