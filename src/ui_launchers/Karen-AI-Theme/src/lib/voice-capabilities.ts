/**
 * Backend-owned, versioned modality catalog and durable voice preference.
 *
 * Do not infer available engines from a plugin manifest, browser API, or UI
 * default. Only authenticated and authorized VoiceRuntime receipts count.
 */

export type VoiceIdentity = { id: string; name: string; language: string };

export type VoiceEngine = {
  engine_id: string;
  display_name: string;
  plugin_version: string;
  modality: 'tts';
  status: 'ready';
  model_id: string;
  model_revision: string;
  features: {
    synthesis: true;
    streaming: boolean;
    voice_cloning: boolean;
  };
  voices: VoiceIdentity[];
};

export type VoiceCatalog = {
  contract_version: '1.0.0';
  engines: VoiceEngine[];
};

export type VoiceSelection = {
  engine_id: string | null;
  voice_id: string | null;
};

export type VoiceSelectionResponse = {
  voice: VoiceSelection;
  available: boolean;
};

const safeEngineId = (value: unknown): value is string =>
  typeof value === 'string' && /^[a-z][a-z0-9-]{0,49}$/.test(value);

const safeVoiceId = (value: unknown): value is string =>
  typeof value === 'string' && /^[A-Za-z][A-Za-z0-9_-]{0,95}$/.test(value);

const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;

export function parseVoiceCatalog(value: unknown): VoiceCatalog {
  const top = record(value);
  if (!top || top.contract_version !== '1.0.0' || !Array.isArray(top.engines)) {
    throw new Error('Karen did not return a supported voice capability catalog');
  }
  if (top.engines.length > 64) throw new Error('Voice catalog exceeds limits');
  const engines: VoiceEngine[] = [];
  const seen = new Set<string>();
  for (const item of top.engines) {
    const engine = record(item);
    const features = record(engine?.features);
    if (
      !engine || !safeEngineId(engine.engine_id) || seen.has(engine.engine_id) ||
      engine.status !== 'ready' || engine.modality !== 'tts' ||
      typeof engine.display_name !== 'string' || !engine.display_name.trim() ||
      typeof engine.plugin_version !== 'string' ||
      typeof engine.model_id !== 'string' ||
      typeof engine.model_revision !== 'string' ||
      !features || features.synthesis !== true ||
      typeof features.streaming !== 'boolean' ||
      typeof features.voice_cloning !== 'boolean' ||
      !Array.isArray(engine.voices) || engine.voices.length === 0 ||
      engine.voices.length > 32
    ) {
      throw new Error('Karen returned an invalid voice engine');
    }
    seen.add(engine.engine_id);
    const voices: VoiceIdentity[] = [];
    const voiceIds = new Set<string>();
    for (const rawVoice of engine.voices) {
      const voice = record(rawVoice);
      if (!voice || !safeVoiceId(voice.id) || voiceIds.has(voice.id) ||
          typeof voice.name !== 'string' || !voice.name.trim() ||
          typeof voice.language !== 'string' || !voice.language.trim()) {
        throw new Error('Karen returned an invalid voice entry');
      }
      voiceIds.add(voice.id);
      voices.push({ id: voice.id, name: voice.name, language: voice.language });
    }
    engines.push({
      engine_id: engine.engine_id,
      display_name: engine.display_name,
      plugin_version: engine.plugin_version,
      modality: 'tts',
      status: 'ready',
      model_id: engine.model_id,
      model_revision: engine.model_revision,
      features: {
        synthesis: true,
        streaming: features.streaming,
        voice_cloning: features.voice_cloning,
      },
      voices,
    });
  }
  return { contract_version: '1.0.0', engines };
}

export function parseVoiceSelection(value: unknown): VoiceSelectionResponse {
  const top = record(value);
  const voice = record(top?.voice);
  if (
    !top || !voice || typeof top.available !== 'boolean' ||
    (voice.engine_id !== null && !safeEngineId(voice.engine_id)) ||
    (voice.voice_id !== null && !safeVoiceId(voice.voice_id)) ||
    (voice.engine_id === null) !== (voice.voice_id === null)
  ) {
    throw new Error('Karen did not return a valid saved voice preference');
  }
  return {
    voice: { engine_id: voice.engine_id as string | null, voice_id: voice.voice_id as string | null },
    available: top.available,
  };
}
