"use client";

/**
 * First-class Pocket TTS consumer workspace.
 *
 * This page is a host-owned plugin presentation, not a plugin-supplied bundle
 * or a second model/runtime authority. Model downloads are delegated to the
 * existing governed worker, and playable voice/read-aloud preferences remain
 * owned by VoiceRuntime and LocalVoiceEngineSettings.
 */
import { useState } from "react";
import {
  AudioLines,
  CheckCircle2,
  Headphones,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Volume2,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import LocalVoiceEngineSettings from "@/components/settings/LocalVoiceEngineSettings";
import { usePluginRegistry } from "@/plugin_host/registry";
import { PluginRecommendedModels } from "./PluginRecommendedModels";

const POCKET_PLUGIN_ID = "pocket-tts";

type Props = {
  onOpenVoiceStudio?: () => void;
  onOpenPlugins?: () => void;
};

export default function PocketTTSWorkspace({
  onOpenVoiceStudio,
  onOpenPlugins,
}: Props) {
  const { plugins, loading, error, refresh } = usePluginRegistry();
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const [viewRevision, setViewRevision] = useState(0);
  const installed = plugins.find((entry) => entry.id === POCKET_PLUGIN_ID);
  const enabled = installed?.enabled === true;

  const refreshAll = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshError(false);
    try {
      await refresh();
      // Remount both host-owned views so the model worker receipts, live
      // engine catalog, and account voice selection are freshly retrieved.
      // This does not mutate the plugin or assume model readiness.
      setViewRevision((previous) => previous + 1);
    } catch {
      setRefreshError(true);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <main
      className="mx-auto w-full max-w-6xl space-y-6 overflow-y-auto p-4 pb-10 md:p-7"
      aria-label="Pocket TTS plugin workspace"
      data-testid="pocket-tts-workspace"
    >
      <header className="rounded-2xl border bg-card p-5 shadow-sm md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div className="flex items-start gap-4">
            <div className="rounded-2xl bg-primary/10 p-3 text-primary">
              <AudioLines className="h-7 w-7" aria-hidden="true" />
            </div>
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
                Plugins / Audio &amp; speech
              </p>
              <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
                Pocket TTS
              </h1>
              <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                Private, CPU-first text-to-speech powered by a licensed, locally installed
                Kyutai model. Explore verified voices, hear a real sample, and choose
                how Karen reads responses aloud.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {onOpenVoiceStudio && (
              <Button type="button" variant="outline" onClick={onOpenVoiceStudio}>
                <Headphones className="mr-2 h-4 w-4" aria-hidden="true" />
                Open Voice Studio
              </Button>
            )}
            <Button type="button" variant="outline" disabled={refreshing}
              onClick={() => void refreshAll()} aria-label="Refresh Pocket TTS status">
              <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
                aria-hidden="true" />
              Refresh status
            </Button>
          </div>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border bg-muted/30 px-3 py-1.5" role="status"
            data-testid="pocket-tts-plugin-status">
            {loading || refreshing ? (
              <><Loader2 className="mr-1 inline h-3 w-3 animate-spin" />Checking plugin…</>
            ) : error || refreshError ? (
              "Plugin status unavailable"
            ) : enabled ? (
              <><CheckCircle2 className="mr-1 inline h-3 w-3 text-emerald-600" />Plugin enabled</>
            ) : installed ? (
              `Plugin ${installed.rawStatus || "not enabled"}`
            ) : (
              "Plugin not found in your authorized catalog"
            )}
          </span>
          {installed?.version && (
            <span className="rounded-full border px-3 py-1.5">Plugin v{installed.version}</span>
          )}
          <span className="rounded-full border px-3 py-1.5">
            Model and voice readiness verified separately
          </span>
        </div>
      </header>

      {(error || refreshError) && (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Plugin inventory unavailable</AlertTitle>
          <AlertDescription>
            Karen could not refresh the authenticated plugin catalog. No enabled
            status or model readiness has been assumed.
          </AlertDescription>
        </Alert>
      )}

      {!loading && !error && !refreshError && !enabled && (
        <Alert data-testid="pocket-tts-plugin-not-enabled">
          <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Pocket TTS is not enabled</AlertTitle>
          <AlertDescription>
            Installing the model is separate from enabling the plugin. A workspace
            administrator can manage its lifecycle in Tools &amp; plugins.
            The voice picker remains unavailable until Karen verifies both.
            {onOpenPlugins && (
              <Button type="button" variant="link" onClick={onOpenPlugins}
                className="ml-1 h-auto p-0 align-baseline">
                Open plugin management
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <ShieldCheck className="h-4 w-4 text-primary" /> Governed model
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Downloaded only by Karen&apos;s audited model worker after reviewing
            the exact upstream revision and license.
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Headphones className="h-4 w-4 text-primary" /> Installed voices
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Only voices returned by the authenticated live synthesis catalog can
            be selected or previewed.
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Volume2 className="h-4 w-4 text-primary" /> Read aloud
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Save your voice to your account. Streaming, voice cloning, and
            automatic browser fallback are not enabled by Pocket TTS.
          </CardContent>
        </Card>
      </div>

      <section className="space-y-3" aria-label="Pocket TTS model installation"
        data-testid="pocket-tts-installation">
        <div>
          <h2 className="text-lg font-semibold">1. Model installation</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Review terms and queue the recommended model using Karen&apos;s existing
            download service. Job completion is not a voice-ready guarantee.
          </p>
        </div>
        <PluginRecommendedModels key={`pocket-model-${viewRevision}`}
          pluginId={POCKET_PLUGIN_ID} />
      </section>

      <section className="space-y-3" aria-label="Pocket TTS voices and playback"
        data-testid="pocket-tts-voice-lab">
        <div>
          <h2 className="text-lg font-semibold">2. Voice lab</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            This tests real, governed local synthesis. Preview is disabled when
            Pocket TTS is not in the live voice-engine catalog.
          </p>
        </div>
        <LocalVoiceEngineSettings
          key={`pocket-voice-${viewRevision}`}
          engineFilter={POCKET_PLUGIN_ID}
        />
      </section>
    </main>
  );
}
