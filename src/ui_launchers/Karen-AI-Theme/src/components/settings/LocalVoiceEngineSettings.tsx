"use client";

/** Governed local speech engines. Never infer readiness from plugin metadata. */
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Check, CircleCheck, Headphones, Loader2, Play, RefreshCw, Square, Volume2 } from "lucide-react";
import { apiClient, ApiError } from "@/lib/api";
import type { VoiceCatalog, VoiceEngine, VoiceSelectionResponse } from "@/lib/voice-capabilities";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";

const BROWSER = "_browser_speech_";
const PREVIEW_TEXT = "Hello, I am Karen. This is a local voice preview.";
const MAX_PREVIEW_TEXT_CHARS = 480;

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Sign in to discover your permitted local speech engines.";
    if (error.status === 403) return "Your account is not authorized to use this speech engine.";
    if (error.status === 503) return "Karen's local voice runtime is unavailable.";
  }
  return "Karen could not verify the local voice engine catalog.";
}

export default function LocalVoiceEngineSettings({ engineFilter }: { engineFilter?: string } = {}) {
  const { toast } = useToast();
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [catalog, setCatalog] = useState<VoiceCatalog | null>(null);
  const [saved, setSaved] = useState<VoiceSelectionResponse | null>(null);
  const [engineId, setEngineId] = useState<string>(BROWSER);
  const [voiceId, setVoiceId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewText, setPreviewText] = useState(PREVIEW_TEXT);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const mountedRef = useRef(false);
  const revisionRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    setPreviewing(false);
  }, []);

  const refresh = useCallback(async (epoch: number) => {
    setStatus("loading");
    setError(null);
    try {
      const [engines, preference] = await Promise.all([
        apiClient.getVoiceEngineCatalog(),
        apiClient.getVoiceSelection(),
      ]);
      if (revisionRef.current !== epoch) return;
      setCatalog(engines);
      setSaved(preference);
      if (engineFilter) {
        const available = engines.engines.find((entry) => entry.engine_id === engineFilter);
        const savedVoice = preference.voice.engine_id === engineFilter &&
          available?.voices.some((voice) => voice.id === preference.voice.voice_id)
          ? preference.voice.voice_id : null;
        setEngineId(engineFilter);
        setVoiceId(savedVoice ?? available?.voices[0]?.id ?? "");
      } else {
        setEngineId(preference.voice.engine_id ?? BROWSER);
        setVoiceId(preference.voice.voice_id ?? "");
      }
      setStatus("ready");
    } catch (cause) {
      if (revisionRef.current !== epoch) return;
      setCatalog(null);
      setSaved(null);
      setStatus("failed");
      setError(errorMessage(cause));
    }
  }, [engineFilter]);

  useEffect(() => {
    mountedRef.current = true;
    const epoch = ++revisionRef.current;
    void refresh(epoch);
    return () => {
      mountedRef.current = false;
      revisionRef.current += 1;
      abortRef.current?.abort();
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = "";
        audioRef.current = null;
      }
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, [refresh]);

  // Filtering is a presentation contract. Runtime still owns which
  // engines and voices actually exist and may execute.
  const visibleEngines = catalog?.engines.filter(
    (entry) => !engineFilter || entry.engine_id === engineFilter,
  ) ?? [];
  const selectedEngine: VoiceEngine | undefined = visibleEngines.find(
    (item) => item.engine_id === engineId,
  );
  const selectedVoice = selectedEngine?.voices.find((voice) => voice.id === voiceId);
  const storedMissing = Boolean(
    saved?.voice.engine_id && (!saved.available ||
      !catalog?.engines.some((engine) =>
        engine.engine_id === saved.voice.engine_id &&
        engine.voices.some((voice) => voice.id === saved.voice.voice_id)
      )),
  );

  const changeEngine = (value: string) => {
    if (savingRef.current) return;
    stop();
    setError(null);
    setEngineId(value);
    const next = catalog?.engines.find((engine) => engine.engine_id === value);
    setVoiceId(next?.voices[0]?.id ?? "");
  };

  const preview = async () => {
    if (previewing) {
      stop();
      return;
    }
    if (!selectedEngine || !selectedVoice || savingRef.current ||
        !previewText.trim() || previewText.length > MAX_PREVIEW_TEXT_CHARS) return;
    stop();
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    setPreviewing(true);
    try {
      const blob = await apiClient.synthesizeLocalVoice(
        selectedEngine.engine_id, selectedVoice.id, previewText.trim(), controller.signal,
      );
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      objectUrlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      // Old audio events can arrive after Stop, source change, or refresh.
      // A retired session must never stop a later preview or show its error.
      audio.onended = () => {
        if (audioRef.current === audio && abortRef.current === controller) stop();
      };
      audio.onerror = () => {
        if (audioRef.current !== audio || abortRef.current !== controller) return;
        setError("Karen's verified audio could not be played by this browser.");
        stop();
      };
      await audio.play();
    } catch {
      if (!controller.signal.aborted) {
        setError("Karen could not complete the local voice preview. Verify the engine and try again.");
        stop();
      }
    }
  };

  const save = async () => {
    if (savingRef.current || status !== "ready") return;
    if (engineFilter && (!selectedEngine || !selectedVoice)) {
      setError("Pocket TTS must be verified and a real voice selected before saving.");
      return;
    }
    if (engineId !== BROWSER && (!selectedEngine || !selectedVoice)) {
      setError("Choose a currently available local voice before saving.");
      return;
    }
    const requestedEngine = selectedEngine?.engine_id ?? null;
    const requestedVoice = selectedVoice?.id ?? null;
    const generation = revisionRef.current;
    savingRef.current = true;
    setSaving(true);
    setError(null);
    try {
      const receipt = await apiClient.setVoiceSelection(requestedEngine, requestedVoice);
      if (revisionRef.current !== generation) return;
      if (receipt.voice.engine_id !== requestedEngine ||
          receipt.voice.voice_id !== requestedVoice ||
          (requestedEngine !== null && !receipt.available)) {
        throw new Error("voice_preference_receipt_mismatch");
      }
      // The Settings panel must follow the same durability truth contract as
      // the Copilot voice dock: a write receipt alone is not a verified save.
      const persisted = await apiClient.getVoiceSelection();
      if (revisionRef.current !== generation) return;
      if (persisted.voice.engine_id !== requestedEngine ||
          persisted.voice.voice_id !== requestedVoice ||
          (requestedEngine !== null && !persisted.available)) {
        throw new Error("voice_preference_readback_mismatch");
      }
      setSaved(persisted);
      toast({
        title: "Speech engine preference saved",
        description: "Karen confirmed this choice on your authenticated user record.",
      });
    } catch {
      if (revisionRef.current === generation) {
        setError("Karen could not verify the saved voice preference. Refresh before retrying.");
        toast({
          title: "Speech engine preference not saved",
          description: "Karen did not verify the durable preference update.",
          variant: "destructive",
        });
      }
    } finally {
      savingRef.current = false;
      if (mountedRef.current) {
        // A refresh invalidates the old save response, but must not leave the
        // Save button disabled. Re-read after the in-flight write finishes so
        // an earlier refresh cannot present a stale persisted preference.
        setSaving(false);
        if (revisionRef.current !== generation) {
          void refresh(++revisionRef.current);
        }
      }
    }
  };

  const savedEngine = catalog?.engines.find(
    (entry) => entry.engine_id === saved?.voice.engine_id,
  );
  const savedVoice = savedEngine?.voices.find((voice) => voice.id === saved?.voice.voice_id);
  const savedLocal = saved?.voice.engine_id !== null && saved?.voice.engine_id !== undefined;
  const savedLabel = savedLocal
    ? storedMissing
      ? "Saved local voice unavailable"
      : savedEngine && savedVoice
        ? `${savedEngine.display_name} · ${savedVoice.name}`
        : "Local voice not verified"
    : "Browser speech";
  const hasUnsavedSelection = saved !== null &&
    (engineId !== (saved.voice.engine_id ?? BROWSER) ||
     voiceId !== (saved.voice.voice_id ?? ""));
  const previewReady = status === "ready" && !saving &&
    Boolean(selectedEngine && selectedVoice && previewText.trim()) &&
    previewText.length <= MAX_PREVIEW_TEXT_CHARS;

  return (
    <Card data-testid="karen-local-voice-studio">
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Headphones className="h-6 w-6" aria-hidden="true" />
            </div>
            <div>
              <CardTitle className="text-xl">{engineFilter ? "Pocket TTS Voice Lab" : "Local Voice Studio"}</CardTitle>
              <CardDescription className="mt-1 max-w-xl">
                {engineFilter
                  ? "Choose an installed Pocket TTS voice, generate a real local sample, and save it for Karen’s Read aloud feature."
                  : "Choose your authorized speech engine, hear an actual model-backed sample, and save the voice Karen uses when you choose Read aloud."}
              </CardDescription>
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs text-muted-foreground"
            role="status" data-testid="voice-studio-readiness">
            {status === "loading"
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              : status === "ready" && Boolean(visibleEngines.length)
                ? <CircleCheck className="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" />
                : <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />}
            {status === "loading" ? "Verifying engines" :
              status === "failed" ? "Catalog unavailable" :
                visibleEngines.length ? `${visibleEngines.length} local engine${visibleEngines.length === 1 ? "" : "s"} ready` : "No local engines ready"}
          </span>
        </div>
        {status === "ready" && saved && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-sm">
            <span className="text-muted-foreground">Account selection:</span>
            <span className="font-medium" data-testid="voice-studio-saved-selection">{savedLabel}</span>
            {!storedMissing && savedLocal && saved?.available && (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-400">
                <Check className="h-3 w-3" aria-hidden="true" /> Verified
              </span>
            )}
            {hasUnsavedSelection && <span className="text-xs text-muted-foreground">Unsaved changes</span>}
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-5">
        {status === "loading" && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Verifying installed local speech engines…
          </p>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Voice Studio needs attention</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {status === "ready" && (
          <>
            {!visibleEngines.length && (
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>{engineFilter ? "Pocket TTS Not Ready" : "No Local TTS Plugin Ready"}</AlertTitle>
                <AlertDescription>
                  {engineFilter
                    ? "An administrator must license and install the pinned Pocket model and enable the trusted plugin. Only a backend-verified model and voice can become available here."
                    : "An enabled plugin is not necessarily ready for speech. An administrator must install and license its approved model through Models & Runtime → Model Downloads, enable the trusted plugin, then refresh here. No browser fallback is selected automatically."}
                </AlertDescription>
              </Alert>
            )}
            {storedMissing && (
              <p role="alert" className="text-sm text-destructive">
                Your saved local speech engine or voice is no longer available.
                Select another verified engine or explicitly return to browser speech.
              </p>
            )}
            <div className="space-y-2">
              <Label htmlFor="karen-local-engine">Speech output source</Label>
              {engineFilter ? (
                <div id="karen-local-engine" role="status" className="rounded-lg border bg-muted/20 px-3 py-2 text-sm" data-testid="pocket-tts-engine-scope">
                  Pocket TTS · governed local CPU synthesis
                </div>
              ) : <Select value={engineId === BROWSER || selectedEngine ? engineId : "_missing_saved_"}
                disabled={saving} onValueChange={changeEngine}>
                <SelectTrigger id="karen-local-engine"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {engineId !== BROWSER && !selectedEngine &&
                    <SelectItem value="_missing_saved_" disabled>Saved engine unavailable</SelectItem>}
                  <SelectItem value={BROWSER}>Browser speech (device-dependent)</SelectItem>
                  {catalog?.engines.map((engine) => (
                    <SelectItem key={engine.engine_id} value={engine.engine_id}>
                      {engine.display_name} · {engine.modality.toUpperCase()} · Local
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>}
              <p className="text-xs text-muted-foreground">
                {engineFilter
                  ? "Only Karen’s verified Pocket TTS model may synthesize audio here. No browser speech or other engine is substituted."
                  : "Local speech is generated through Karen’s authenticated runtime. Browser speech depends on your device and may use vendor services."}
              </p>
            </div>
            {selectedEngine ? (
              <section aria-label="Local voice preview and selection" className="space-y-4 rounded-xl border p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h3 className="text-base font-semibold">{selectedEngine.display_name}</h3>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Model: {selectedEngine.model_id} · Version: {selectedEngine.plugin_version}
                    </p>
                    <p className="mt-0.5 break-all font-mono text-[11px] text-muted-foreground">
                      Verified model revision: {selectedEngine.model_revision}
                    </p>
                  </div>
                  <span className="rounded-full border px-2 py-1 text-xs text-muted-foreground">
                    {selectedEngine.features.streaming ? "Streaming supported" : "Complete WAV"}
                  </span>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="karen-local-voice">Installed voice</Label>
                  <Select value={selectedVoice?.id ?? ""} disabled={saving}
                    onValueChange={(id) => { stop(); setVoiceId(id); }}>
                    <SelectTrigger id="karen-local-voice">
                      <SelectValue placeholder="Select a verified voice" />
                    </SelectTrigger>
                    <SelectContent>
                      {selectedEngine.voices.map((voice) => (
                        <SelectItem key={voice.id} value={voice.id}>{voice.name} ({voice.language})</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" role="group" aria-label="Available local voices">
                    {selectedEngine.voices.map((voice) => (
                      <button type="button" key={voice.id} disabled={saving}
                        aria-label={`Choose ${voice.name} local voice`}
                        aria-pressed={selectedVoice?.id === voice.id}
                        onClick={() => { stop(); setVoiceId(voice.id); }}
                        className={`flex min-h-14 items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50 ${
                          selectedVoice?.id === voice.id ? "border-primary bg-primary/5" : "hover:bg-muted/50"
                        }`}>
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{voice.name}</span>
                          <span className="block text-xs text-muted-foreground">{voice.language}</span>
                        </span>
                        {selectedVoice?.id === voice.id && <Check className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="karen-local-voice-sample">Try a spoken sample</Label>
                  <textarea id="karen-local-voice-sample" value={previewText} maxLength={MAX_PREVIEW_TEXT_CHARS}
                    disabled={saving || previewing}
                    onChange={(event) => setPreviewText(event.target.value)}
                    rows={3} className="w-full resize-y rounded-lg border border-input bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
                    aria-describedby="karen-local-voice-sample-help" />
                  <div id="karen-local-voice-sample-help" className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span>Only sent to your selected local engine when you press Preview. Not added to chat.</span>
                    <span>{previewText.length}/{MAX_PREVIEW_TEXT_CHARS}</span>
                  </div>
                  <Button type="button" variant="outline" disabled={!previewing && !previewReady}
                    onClick={() => void preview()}>
                    {previewing ? <Square className="mr-2 h-4 w-4" /> : <Play className="mr-2 h-4 w-4" />}
                    {previewing ? "Stop local preview" : "Preview local voice"}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  {selectedEngine.features.voice_cloning
                    ? "Voice cloning is declared available by this authorized engine."
                    : "Voice cloning is not available for this engine."}
                  {" "}Model availability can change if an administrator disables the plugin or revokes its installation.
                </p>
              </section>
            ) : (
              <div className="rounded-xl border bg-muted/20 p-4 text-sm text-muted-foreground">
                {engineFilter
                  ? "Pocket TTS voice controls unlock only when an installed, enabled model passes Karen’s live runtime checks."
                  : "Browser speech is a separate device feature. Use the Browser voice panel below to choose and preview an installed browser voice."}
              </div>
            )}
          </>
        )}
        <Button type="button" variant="outline"
          onClick={() => { stop(); void refresh(++revisionRef.current); }}>
          <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
          Refresh local engines
        </Button>
      </CardContent>
      <CardFooter className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          <Volume2 className="h-4 w-4" aria-hidden="true" />
          Read aloud remains opt-in on every assistant reply.
        </span>
        <Button type="button" onClick={() => void save()}
          disabled={status !== "ready" || saving || (engineFilter ? !selectedEngine || !selectedVoice : engineId !== BROWSER && !selectedVoice)}>
          {saving ? "Saving…" : "Save speech engine"}
        </Button>
      </CardFooter>
    </Card>
  );
}
