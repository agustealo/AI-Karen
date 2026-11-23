"use client";

/**
 * Browser voice preference coexists with backend-governed local engines. Neither may claim that a missing
 * Web Speech voice is a server outage or that a default voice can play.
 * Karen's authenticated VoiceRuntime owns local model capabilities.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, RefreshCw, Volume2 } from "lucide-react";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useToast } from "@/hooks/use-toast";
import { readPreferredBrowserVoiceURI, persistPreferredBrowserVoiceURI } from "@/lib/browser-voice-preference";
import LocalVoiceEngineSettings from "@/components/settings/LocalVoiceEngineSettings";
import { stopAssistantPlayback } from "@/components/chat/KarenBrowserSpeechPlayback";

const DEFAULT_VOICE_SENTINEL = "_DEFAULT_VOICE_";
const DISCOVERY_DELAYS_MS = [250, 1000, 3000] as const;
type VoiceStatus = "loading" | "ready" | "empty" | "unsupported" | "failed";

export default function VoiceSettings() {
  const { toast } = useToast();
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [status, setStatus] = useState<VoiceStatus>("loading");
  const [selectedVoiceURI, setSelectedVoiceURI] = useState<string | null>(null);
  const [cycle, setCycle] = useState(0);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewRef = useRef<SpeechSynthesisUtterance | null>(null);

  useEffect(() => {
    setSelectedVoiceURI(readPreferredBrowserVoiceURI());
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis ||
        typeof window.speechSynthesis.getVoices !== "function") {
      setStatus("unsupported");
      return;
    }
    const synthesis = window.speechSynthesis;
    let active = true;
    const timers: ReturnType<typeof setTimeout>[] = [];
    let finalAttempt = false;

    const refresh = () => {
      if (!active) return;
      try {
        // voiceURI identifies the actual speech engine voice, not the row index.
        const unique = new Map<string, SpeechSynthesisVoice>();
        for (const voice of synthesis.getVoices()) {
          if (voice.voiceURI && !unique.has(voice.voiceURI)) {
            unique.set(voice.voiceURI, voice);
          }
        }
        const inventory = [...unique.values()];
        setVoices(inventory);
        if (inventory.length) {
          setStatus("ready");
        } else {
          setStatus(finalAttempt ? "empty" : "loading");
        }
      } catch {
        setStatus("failed");
        setVoices([]);
      }
    };
    const onVoicesChanged = () => refresh();
    const onVisibility = () => {
      if (document.visibilityState === "visible") refresh();
    };
    setStatus("loading");
    refresh();
    synthesis.addEventListener("voiceschanged", onVoicesChanged);
    document.addEventListener("visibilitychange", onVisibility);
    DISCOVERY_DELAYS_MS.forEach((delay, index) => {
      timers.push(setTimeout(() => {
        if (index === DISCOVERY_DELAYS_MS.length - 1) finalAttempt = true;
        refresh();
      }, delay));
    });
    return () => {
      active = false;
      timers.forEach(clearTimeout);
      synthesis.removeEventListener("voiceschanged", onVoicesChanged);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [cycle]);

  const releasePreview = useCallback(() => {
    // speechSynthesis is global to the tab. Never cancel audio owned by
    // chat read-aloud when this settings panel has no active preview.
    const owned = previewRef.current !== null;
    previewRef.current = null;
    if (owned && typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
  }, []);

  useEffect(() => () => { releasePreview(); }, [releasePreview]);

  const stopPreview = useCallback(() => {
    releasePreview();
    setPreviewing(false);
  }, [releasePreview]);

  const selectedVoice = voices.find((voice) => voice.voiceURI === selectedVoiceURI);
  const missingSavedVoice = Boolean(selectedVoiceURI && status === "ready" && !selectedVoice);
  const activeSelection = selectedVoice || voices.find((voice) => voice.default) || voices[0];

  const previewVoice = () => {
    if (previewing) {
      stopPreview();
      return;
    }
    if (status !== "ready" || !activeSelection ||
        typeof SpeechSynthesisUtterance === "undefined") {
      setPreviewError("No verified browser voice is available for playback.");
      return;
    }
    // Retire chat playback through its canonical owner first; a raw
    // speechSynthesis.cancel() would leave its active state unresolved.
    stopAssistantPlayback();
    stopPreview();
    setPreviewError(null);
    const speech = new SpeechSynthesisUtterance("Hello, I am Karen. This is my voice preview.");
    speech.voice = activeSelection;
    speech.lang = activeSelection.lang;
    speech.onend = () => {
      if (previewRef.current === speech) {
        previewRef.current = null;
        setPreviewing(false);
      }
    };
    speech.onerror = () => {
      if (previewRef.current === speech) {
        previewRef.current = null;
        setPreviewing(false);
        setPreviewError("This browser could not play the selected voice.");
      }
    };
    previewRef.current = speech;
    setPreviewing(true);
    try {
      window.speechSynthesis.speak(speech);
    } catch {
      previewRef.current = null;
      setPreviewing(false);
      setPreviewError("This browser could not start speech playback.");
    }
  };

  const saveSettings = () => {
    if (missingSavedVoice) {
      toast({
        title: "Voice unavailable",
        description: "Select an available voice or reset to the default before saving.",
        variant: "destructive",
      });
      return;
    }
    try {
      persistPreferredBrowserVoiceURI(selectedVoiceURI);
      toast({
        title: "Browser voice preference saved",
        description: "The preference is stored on this device, not in Karen's server settings.",
      });
    } catch {
      toast({
        title: "Voice preference not saved",
        description: "Browser storage is unavailable or contains invalid settings.",
        variant: "destructive",
      });
    }
  };

  const resetToDefaults = () => {
    try {
      persistPreferredBrowserVoiceURI(null);
      stopPreview();
      setSelectedVoiceURI(null);
      toast({ title: "Browser voice preference reset" });
    } catch {
      toast({
        title: "Voice preference not reset",
        description: "Browser storage is unavailable.",
        variant: "destructive",
      });
    }
  };

  return (
    <div className="space-y-4">
      <LocalVoiceEngineSettings />
      <Card>
      <CardHeader>
        <CardTitle className="text-lg">Text-to-Speech Voice</CardTitle>
        <CardDescription>
          Select and preview a browser voice for spoken replies. Local model-based
          speech synthesis is a separate Karen runtime capability.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {status === "loading" && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Checking browser speech voices…
          </p>
        )}
        {(status === "empty" || status === "unsupported" || status === "failed") && (
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>
              {status === "empty" ? "No Browser Voices Found" :
                status === "unsupported" ? "Browser Speech Unsupported" : "Voice Discovery Failed"}
            </AlertTitle>
            <AlertDescription>
              {status === "empty"
                ? "This browser reported no installed speech voices. Check the operating system speech service or try another browser. Spoken output cannot be assumed to work."
                : status === "unsupported"
                  ? "This browser does not expose speech synthesis."
                  : "The browser failed to enumerate speech voices. Retry discovery."}
            </AlertDescription>
          </Alert>
        )}
        {status === "ready" && (
          <div className="space-y-2">
            <Label htmlFor="tts-voice">Browser voice</Label>
            <Select
              value={selectedVoice ? selectedVoice.voiceURI : DEFAULT_VOICE_SENTINEL}
              onValueChange={(value) => {
                stopPreview();
                setSelectedVoiceURI(value === DEFAULT_VOICE_SENTINEL ? null : value);
              }}
            >
              <SelectTrigger id="tts-voice">
                <SelectValue placeholder="Browser default voice" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DEFAULT_VOICE_SENTINEL}>Browser default voice</SelectItem>
                {voices.map((voice) => (
                  <SelectItem key={voice.voiceURI} value={voice.voiceURI}>
                    {voice.name} ({voice.lang}) {voice.default ? "[Default]" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {missingSavedVoice && (
              <p role="alert" className="text-sm text-destructive">
                Your previously selected voice is no longer available on this device.
                Select a new one or reset to the browser default.
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              Browser voices and quality depend on your operating system. Voice
              preview does not send a chat message.
            </p>
          </div>
        )}
        {previewError && <p role="alert" className="text-sm text-destructive">{previewError}</p>}
        <div className="flex flex-wrap gap-2">
          <Button
            type="button" variant="outline"
            onClick={() => { stopPreview(); setCycle((current) => current + 1); }}
            aria-label="Refresh browser voices"
          >
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />Refresh voices
          </Button>
          <Button
            type="button" variant="outline" onClick={previewVoice}
            disabled={status !== "ready" || !activeSelection}
          >
            <Volume2 className="mr-2 h-4 w-4" aria-hidden="true" />
            {previewing ? "Stop preview" : "Preview voice"}
          </Button>
        </div>
      </CardContent>
      <CardFooter className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" onClick={resetToDefaults}>Reset to Default</Button>
        <Button type="button" onClick={saveSettings} disabled={status === "loading" || missingSavedVoice}>
          Save Settings
        </Button>
      </CardFooter>
      </Card>
    </div>
  );
}
