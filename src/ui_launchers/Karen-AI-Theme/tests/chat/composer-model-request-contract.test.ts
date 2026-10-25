import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('assistant-ui model request transport', () => {
  it('uses only canonical AG-UI request hints with automatic routing as default', () => {
    const chat = readFileSync(resolve(process.cwd(), 'src/components/chat/assistant-ui/KarenAssistantChat.tsx'), 'utf8');
    const chooser = readFileSync(resolve(process.cwd(), 'src/components/chat/assistant-ui/KarenComposerRuntimeCatalog.tsx'), 'utf8');
    expect(chat).toContain('preferred_llm_provider: modelRequestRef.current.provider');
    expect(chat).toContain('preferred_model: modelRequestRef.current.model');
    expect(chat).toContain('[threadId, workspaceRunId]');
    expect(chat).toContain('modelRequestRef.current = modelRequest');
    expect(chooser).toContain('Automatic routing (Karen default)');
    expect(chooser).toContain('model.available === true');
    expect(chooser).toContain('provider.healthy === true');
    expect(chooser).toContain('provider.configured === true');
    expect(chooser).toContain('onSelectionChange(null)');
  });
});
