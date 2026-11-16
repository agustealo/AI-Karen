"use client";

/** Governed local speech engines. Never infer readiness from plugin metadata. */
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, Play, RefreshCw, Square } from "lucide-react";
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

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Sign in to discover your permitted local speech engines.";
    if (error.status === 403) return "Your account is not authorized to use this speech engine.";
    if (error.status === 503) return "Karen's local voice runtime is unavailable.";
  }
  return "Karen could not verify the local voice engine catalog.";
}

export default function LocalVoiceEngineSettings() {
  const { toast } = useToast();
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [catalog, setCatalog] = useState<VoiceCatalog | null>(null);
  const [saved, setSaved] = useState<VoiceSelectionResponse | null>(null);
  const [engineId, setEngineId] = useState<string>(BROWSER);
  const [voiceId, setVoiceId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
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
      setEngineId(preference.voice.engine_id ?? BROWSER);
      setVoiceId(preference.voice.voice_id ?? "");
      setStatus("ready");
    } catch (cause) {
      if (revisionRef.current !== epoch) return;
      setCatalog(null);
      setSaved(null);
      setStatus("failed");
      setError(errorMessage(cause));
    }
  }, []);

  useEffect(() => {
    const epoch = ++revisionRef.current;
    void refresh(epoch);
    return () => {
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

  const selectedEngine: VoiceEngine | undefined = catalog?.engines.find(
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
    if (!selectedEngine || !selectedVoice) return;
    stop();
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    setPreviewing(true);
    try {
      const blob = await apiClient.synthesizeLocalVoice(
        selectedEngine.engine_id, selectedVoice.id, PREVIEW_TEXT, controller.signal,
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
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(errorMessage(cause));
        stop();
      }
    }
  };

  const save = async () => {
    if (savingRef.current || status !== "ready") return;
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
      if (revisionRef.current === generation) setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Local Speech Engines</CardTitle>
        <CardDescription>
          Choose a verified, authorized speech plugin. Model-backed voices are
          independent of browser-installed voices, and require local model assets.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {status === "loading" && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Verifying installed local speech engines…
          </p>
        )}
        {error && <Alert><AlertCircle className="h-4 w-4" /><AlertTitle>Local voice unavailable</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
        {status === "ready" && (
          <>
            {!catalog?.engines.length && (
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>No Local TTS Plugin Ready</AlertTitle>
                <AlertDescription>
                  An administrator must enable a trusted speech plugin and install its approved
                  model and voice assets. Browser voices can still be configured below.
                </AlertDescription>
              </Alert>
            )}
            {storedMissing && <p role="alert" className="text-sm text-destructive">
              Your saved local speech engine or voice is no longer available.
              Select another verified engine or return to browser speech.
            </p>}
            <div className="space-y-2">
              <Label htmlFor="karen-local-engine">Speech output source</Label>
              <Select value={engineId === BROWSER || selectedEngine ? engineId : "_missing_saved_"} onValueChange={changeEngine}>
                <SelectTrigger id="karen-local-engine"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {engineId !== BROWSER && !selectedEngine && <SelectItem value="_missing_saved_" disabled>Saved engine unavailable</SelectItem>}
                  <SelectItem value={BROWSER}>Browser speech (device-dependent)</SelectItem>
                  {catalog?.engines.map((engine) => (
                    <SelectItem key={engine.engine_id} value={engine.engine_id}>
                      {engine.display_name} · {engine.modality.toUpperCase()} · Local
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {selectedEngine && (
              <>
                <div className="space-y-2">
                  <Label htmlFor="karen-local-voice">Installed voice</Label>
                  <Select value={selectedVoice?.id ?? ""} onValueChange={(id) => { stop(); setVoiceId(id); }}>
                    <SelectTrigger id="karen-local-voice"><SelectValue placeholder="Select a voice" /></SelectTrigger>
                    <SelectContent>
                      {selectedEngine.voices.map((voice) => (
                        <SelectItem key={voice.id} value={voice.id}>{voice.name} ({voice.language})</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <p className="text-xs text-muted-foreground">
                  Model: {selectedEngine.model_id} · Version: {selectedEngine.plugin_version}
                  {selectedEngine.features.streaming ? " · Streaming" : " · Full WAV"}
                  {selectedEngine.features.voice_cloning ? " · Voice cloning approved" : ""}
                </p>
                <Button type="button" variant="outline" onClick={() => void preview()}>
                  {previewing ? <Square className="mr-2 h-4 w-4" /> : <Play className="mr-2 h-4 w-4" />}
                  {previewing ? "Stop local preview" : "Preview local voice"}
                </Button>
              </>
            )}
          </>
        )}
        <Button type="button" variant="outline" onClick={() => { stop(); void refresh(++revisionRef.current); }}>
          <RefreshCw className="mr-2 h-4 w-4" />Refresh local engines
        </Button>
      </CardContent>
      <CardFooter className="flex justify-end">
        <Button type="button" onClick={() => void save()} disabled={status !== "ready" || saving || (engineId !== BROWSER && !selectedVoice)}>
          {saving ? "Saving…" : "Save speech engine"}
        </Button>
      </CardFooter>
    </Card>
  );
}
