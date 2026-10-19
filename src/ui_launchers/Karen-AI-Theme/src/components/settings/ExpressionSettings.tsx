"use client";

import { useEffect, useState, useCallback, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Bot,
  Loader2,
  Save,
  Settings2,
  Sparkles,
  XCircle,
  InfoIcon,
  Activity,
  Cloud,
  ArrowRight,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { Badge } from '../ui/badge';
import { Label } from '../ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, SelectGroup, SelectLabel } from '../ui/select';
import { Button } from '../ui/button';
import { Separator } from '../ui/separator';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';
import { useAuth } from '@/lib/useAuth';
import { apiClient } from '@/lib/api';
import { cn } from '@/lib/utils';
import { normalizeModelSettingsResponse, type RuntimeSettingsResponse } from '@/lib/model-runtime-inventory';

interface ExpressionEngineConfig {
  enabled?: boolean;
  fallback_eligible?: boolean;
  type?: string;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

interface ExpressionSettingsResponse {
  active_engine: string;
  fallback_order?: string[];
  engines?: Record<string, ExpressionEngineConfig>;
}

type EngineGroup = {
  builtin: Array<ExpressionEngineConfig & { id: string }>;
  local: Array<ExpressionEngineConfig & { id: string }>;
  cloud: Array<ExpressionEngineConfig & { id: string }>;
};

const asString = (value: unknown, fallback = ''): string => {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
};

const getMetadataString = (value: unknown, fallback = 'auto'): string => {
  return asString(value, fallback);
};

export default function ExpressionSettings() {
  const [exprSettings, setExprSettings] = useState<ExpressionSettingsResponse | null>(null);
  const [modelSettings, setModelSettings] = useState<ReturnType<typeof normalizeModelSettingsResponse> | null>(null);
  const [activeEngine, setActiveEngine] = useState('builtin');
  const [fallbackOrder, setFallbackOrder] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const { toast } = useToast();
  const { user } = useAuth();
  const canManageRuntime = Boolean(user?.roles?.some((role) => role === 'admin' || role === 'super_admin'));

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [exprRes, modelRes] = await Promise.all([
        apiClient.get<ExpressionSettingsResponse>('/api/settings/model/expression'),
        apiClient.get<RuntimeSettingsResponse>('/api/settings/model'),
      ]);
      const normalizedModelRes = normalizeModelSettingsResponse(modelRes);
      setExprSettings(exprRes);
      setModelSettings(normalizedModelRes);
      setActiveEngine(exprRes.active_engine);
      setFallbackOrder(exprRes.fallback_order || []);
    } catch {
      toast({
        title: 'Initialization Error',
        description: 'Could not synchronize expression and provider systems.',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  }, [toast]);

  useEffect(() => { void loadData(); }, [loadData]);

  const handleSave = async (engineConfigs?: Record<string, Record<string, unknown>>, newFallbackOrder?: string[]) => {
    if (!canManageRuntime) return;
    setIsSaving(true);
    try {
      const payload: Record<string, unknown> = {
        active_engine: activeEngine,
        fallback_order: newFallbackOrder || fallbackOrder,
      };
      if (engineConfigs) {
        payload.engine_configs = engineConfigs;
      }
      
      const response = await apiClient.put<ExpressionSettingsResponse>('/api/settings/model/expression', payload);
      setExprSettings(response);
      setActiveEngine(response.active_engine);
      setFallbackOrder(response.fallback_order || []);
      toast({ title: 'System Updated', description: 'Expression configuration saved.' });
    } catch {
      toast({
        title: 'Update Failed',
        description: 'The configuration could not be saved.',
        variant: 'destructive',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const updateSequence = (index: number, value: string) => {
    const newOrder = [...fallbackOrder];
    if (value === 'none') {
      newOrder.splice(index, 1);
    } else {
      newOrder[index] = value;
    }
    setFallbackOrder(newOrder);
  };

  const addSequenceStep = () => {
    if (fallbackOrder.length >= 4) return;
    setFallbackOrder([...fallbackOrder, 'builtin']);
  };

  // Group engines by their taxonomy class (use expression settings data)
  const groupedEngines = useMemo<EngineGroup>(() => {
    if (!exprSettings?.engines) return { builtin: [], local: [], cloud: [] };

    const groups: EngineGroup = { builtin: [], local: [], cloud: [] };
    Object.entries(exprSettings?.engines || {}).forEach(([engineId, engineConfig]) => {
      const config = engineConfig as ExpressionEngineConfig;
      // Determine category based on engine type
      if (config.type === 'builtin_provider_engine' || engineId === 'builtin') {
        groups.builtin.push({ id: engineId, ...config });
      } else if (config.type === 'openai_compatible' && !config.fallback_eligible) {
        // Local openai-compatible engines (llama_cpp_server, openai_compatible_local)
        groups.local.push({ id: engineId, ...config });
      } else if (config.fallback_eligible) {
        // External engines that support fallback (openai, gemini, glm)
        groups.cloud.push({ id: engineId, ...config });
      }
    });
    return groups;
  }, [exprSettings]);

  // Group providers by their category (use model settings data)
  const groupedProviders = useMemo(() => {
    if (!modelSettings) return { builtin: [], local: [], cloud: [] };
    
    // Use the library's normalization logic to ensure consistent grouping
    const normalized = normalizeModelSettingsResponse(modelSettings);
    
    return {
      builtin: normalized.builtInProviders || [],
      local: normalized.localProviders || [],
      cloud: [...(normalized.thirdPartyProviders || []), ...(normalized.customProviders || [])]
    };
  }, [modelSettings]);

  const getProviderIcon = (providerId: string) => {
    if (providerId.startsWith('builtin')) return Settings2;
    if (groupedEngines.local.find((engine) => engine.id === providerId)) return Activity;
    if (groupedEngines.cloud.find((engine) => engine.id === providerId)) return Cloud;
    if (providerId === 'builtin') return Settings2;
    if (providerId === 'local') return Activity;
    if (providerId === 'cloud') return Cloud;
    return Bot;
  };

  const getProviderLabel = (providerId: string) => {
    if (providerId === 'builtin') return 'Built-In (Local Runtimes)';
    if (providerId === 'local') return 'Local AI (Ollama/LM Studio)';
    if (providerId === 'cloud') return 'Cloud AI (Managed APIs)';
    const p = modelSettings?.providers?.find((provider) => provider.id === providerId);
    return p?.display_name || providerId;
  };

  // Helper to get models for a provider
  const getModelsForProvider = (providerId: string): Array<{ id: string; name: string; family?: string; source?: string }> => {
    if (providerId === 'builtin') {
        // Collect models from both vLLM and Transformers
        const all = [...groupedProviders.builtin.flatMap((provider) => provider.models || [])];
        // Dedupe
        return Array.from(new Set(all.map((model) => model.id)))
          .map((id) => all.find((model) => model.id === id))
          .filter((model): model is NonNullable<typeof model> => Boolean(model));
    }
    
    if (providerId === 'local') return groupedProviders.local.flatMap((provider) => provider.models || []);
    if (providerId === 'cloud') return groupedProviders.cloud.flatMap((provider) => provider.models || []);
    
    const p = modelSettings?.providers?.find((provider) => provider.id === providerId);
    return p?.models || [];
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // Configuration for the CURRENTLY SELECTED engine/provider in the activeEngine dropdown
  const currentEngineConfig = exprSettings?.engines?.[activeEngine] || {
    enabled: true,
    fallback_eligible: true,
    metadata: {}
  };

  const currentModels = getModelsForProvider(activeEngine);
  const preferredSubProvider = getMetadataString(currentEngineConfig.metadata?.preferred_provider);
  const preferredModel = getMetadataString(currentEngineConfig.metadata?.preferred_model);

  return (
    <div className="space-y-6">
      {!canManageRuntime && <p role="status" className="rounded-lg border bg-muted/20 p-3 text-sm text-muted-foreground">Expression routing is shared runtime configuration. You can review it here, but only an administrator can change the primary engine or fallback order.</p>}
      <Card className="border-border/40 shadow-sm transition-all hover:shadow-md">
        <CardHeader className="border-b bg-muted/20 pb-4">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-xl font-bold flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-primary" /> Expression Engine Management
              </CardTitle>
              <CardDescription>Direct Karen&apos;s cognition through your configured model providers.</CardDescription>
            </div>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="outline" size="icon" className="rounded-full">
                    <InfoIcon className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                  Select which model provider acts as the primary logical engine and define the failover sequence.
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </CardHeader>
        <CardContent className="pt-6 space-y-8">
          
          {/* Main Engine Selector */}
          <div className="space-y-6">
            <div className="space-y-1">
              <Label htmlFor="engine-select" className="text-sm font-semibold uppercase tracking-wider text-muted-foreground/80">Select Engine</Label>
              <p className="text-xs text-muted-foreground">Manage engine availability and primary logical routing.</p>
            </div>

            <div className="flex flex-col gap-6">
              <div className="space-y-4">
                <Select
                  value={activeEngine}
                  onValueChange={setActiveEngine}
                >
                  <SelectTrigger id="engine-select" className="h-14 border-primary/20 bg-background/50 text-base font-bold focus:ring-primary/20 shadow-sm">
                    <SelectValue placeholder="Choose logic engine..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectLabel className="text-[10px] uppercase tracking-widest text-muted-foreground py-2">System Categories</SelectLabel>
                      <SelectItem value="builtin" className="font-bold">Built-In (Internal)</SelectItem>
                      <SelectItem value="local" className="font-bold">Local AI (Ollama/Studio)</SelectItem>
                      <SelectItem value="cloud" className="font-bold">Cloud AI (APIs)</SelectItem>
                    </SelectGroup>
                    
                    <SelectGroup>
                       <SelectLabel className="text-[10px] uppercase tracking-widest text-muted-foreground py-2 border-t mt-2">Named Providers</SelectLabel>
                       {modelSettings?.providers?.map((provider) => (
                         <SelectItem key={provider.id} value={provider.id}>{provider.display_name}</SelectItem>
                       ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>

                {/* Configuration Card for Selected Engine */}
                <div className={cn(
                  "rounded-2xl border p-6 transition-all duration-300",
                  currentEngineConfig.enabled ? "border-primary/30 bg-primary/[0.02] shadow-sm" : "border-border/40 bg-muted/10 opacity-70"
                )}>
                  <div className="flex flex-col gap-8">
                    {/* Header Row */}
                    <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between border-b border-border/40 pb-6">
                      <div className="flex items-start gap-4">
                        <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-primary/30 bg-background text-primary shadow-sm">
                          {(() => {
                             const Icon = getProviderIcon(activeEngine);
                             return <Icon className={cn("h-6 w-6", currentEngineConfig.enabled && "animate-pulse")} />;
                          })()}
                        </div>
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <h4 className="text-sm font-bold uppercase tracking-tight">{getProviderLabel(activeEngine)}</h4>
                            {exprSettings?.active_engine === activeEngine && (
                              <Badge className="h-5 text-[8px] bg-primary text-primary-foreground border-none uppercase tracking-widest px-2">Current Primary</Badge>
                            )}
                            <Badge variant={currentEngineConfig.enabled ? "outline" : "secondary"} className={cn("h-5 text-[8px] uppercase px-1.5 font-bold", currentEngineConfig.enabled ? "text-emerald-500 border-emerald-500/30" : "")}>
                              {currentEngineConfig.enabled ? "Ready" : "Disabled"}
                            </Badge>
                          </div>
                          <p className="text-xs text-muted-foreground">Select specific models and runtimes for this logic layer.</p>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-3">
                        <Button 
                          variant={exprSettings?.active_engine === activeEngine ? "secondary" : "default"}
                          size="sm"
                          className="h-9 text-[10px] font-bold uppercase tracking-widest shadow-sm min-w-[120px]"
                          onClick={() => handleSave()}
                          disabled={!canManageRuntime || isSaving || exprSettings?.active_engine === activeEngine || !currentEngineConfig.enabled}
                        >
                          {exprSettings?.active_engine === activeEngine ? <ShieldCheck className="h-4 w-4 mr-2" /> : <Zap className="h-4 w-4 mr-2" />}
                          {exprSettings?.active_engine === activeEngine ? "Primary Active" : "Set as Primary"}
                        </Button>
                        
                        <div className="flex items-center bg-background/50 rounded-xl border border-border/60 p-1 shadow-inner gap-1">
                          <Button 
                            variant="ghost" 
                            size="sm" 
                            className={cn("h-7 px-3 text-[9px] font-bold uppercase tracking-widest rounded-lg", currentEngineConfig.enabled ? "text-amber-600 hover:bg-amber-50" : "text-emerald-600 hover:bg-emerald-50")}
                            onClick={() => handleSave({ [activeEngine]: { enabled: !currentEngineConfig.enabled } })}
                            disabled={!canManageRuntime || isSaving || activeEngine === 'builtin'}
                          >
                            {currentEngineConfig.enabled ? "Disable" : "Enable"}
                          </Button>
                          <Button 
                            variant={currentEngineConfig.fallback_eligible ? "ghost" : "ghost"}
                            size="sm" 
                            className={cn("h-7 px-3 text-[9px] font-bold uppercase tracking-widest rounded-lg", currentEngineConfig.fallback_eligible ? "text-primary hover:bg-primary/5 shadow-sm bg-background/50" : "text-muted-foreground")}
                            onClick={() => handleSave({ [activeEngine]: { fallback_eligible: !currentEngineConfig.fallback_eligible } })}
                            disabled={!canManageRuntime || isSaving}
                          >
                            {currentEngineConfig.fallback_eligible ? "Fallback ON" : "No Fallback"}
                          </Button>
                        </div>
                      </div>
                    </div>

                    {/* Options Row */}
                    <div className="grid gap-6 md:grid-cols-2">
                       {/* Sub-Provider Selection (Contextual) */}
                       {activeEngine === 'builtin' && (
                         <div className="space-y-3">
                           <Label className="text-[10px] font-bold uppercase tracking-widest text-primary">Runtime Engine</Label>
                           <Select
                             value={preferredSubProvider}
                             onValueChange={(val) => handleSave({ [activeEngine]: { metadata: { preferred_provider: val } } })}
                           >
                             <SelectTrigger className="h-11 bg-background border-border/60 font-semibold text-xs">
                               <SelectValue placeholder="Select internal runtime..." />
                             </SelectTrigger>
                             <SelectContent>
                               <SelectItem value="auto">Automatic (System Choice)</SelectItem>
                               <SelectItem value="vllm">vLLM (Optimized Performance)</SelectItem>
                               <SelectItem value="transformers">Transformers (Broad Compatibility)</SelectItem>
                             </SelectContent>
                           </Select>
                           <p className="text-[10px] text-muted-foreground">Force a specific internal backend or let Karen choose based on model requirements.</p>
                         </div>
                       )}

                       {(activeEngine === 'local' || activeEngine === 'cloud') && (
                         <div className="space-y-3">
                           <Label className="text-[10px] font-bold uppercase tracking-widest text-primary">Preferred Provider</Label>
                           <Select
                             value={preferredSubProvider}
                             onValueChange={(val) => handleSave({ [activeEngine]: { metadata: { preferred_provider: val } } })}
                           >
                             <SelectTrigger className="h-11 bg-background border-border/60 font-semibold text-xs">
                               <SelectValue placeholder="Select provider..." />
                             </SelectTrigger>
                             <SelectContent>
                               <SelectItem value="auto">Automatic (Healthy Default)</SelectItem>
                               {(activeEngine === 'local' ? groupedProviders.local : groupedProviders.cloud).map((provider) => (
                                 <SelectItem key={provider.id} value={provider.id}>{provider.display_name}</SelectItem>
                               ))}
                             </SelectContent>
                           </Select>
                           <p className="text-[10px] text-muted-foreground">Pick a specific provider for this engine slot.</p>
                         </div>
                       )}

                       {/* Model Selection */}
                       <div className="space-y-3">
                          <div className="flex items-center justify-between">
                            <Label className="text-[10px] font-bold uppercase tracking-widest text-primary">Target Model</Label>
                            <Badge variant="secondary" className="h-4 text-[7px] font-mono opacity-60">ID: {preferredModel}</Badge>
                          </div>
                          <Select
                            value={preferredModel}
                            onValueChange={(val) => handleSave({ [activeEngine]: { metadata: { preferred_model: val } } })}
                          >
                            <SelectTrigger className="h-11 bg-background border-border/60 font-semibold text-xs">
                              <SelectValue placeholder="Choose a model..." />
                            </SelectTrigger>
                            <SelectContent className="max-h-[300px]">
                              <SelectItem value="auto">Automatic Selection</SelectItem>
                              {currentModels.map((model) => (
                                <SelectItem key={model.id} value={model.id} className="text-[10px]">
                                   <div className="flex flex-col">
                                      <span className="font-bold">{model.name}</span>
                                      <span className="text-[9px] opacity-60 uppercase">{model.family} • {model.id}</span>
                                   </div>
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <p className="text-[10px] text-muted-foreground">The specific model identifier to request from the engine.</p>
                       </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <Separator className="bg-border/30" />

          {/* Automatic Fallback Sequence */}
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div className="space-y-1">
                <Label className="text-sm font-semibold uppercase tracking-wider text-muted-foreground/80">Automatic Fallback Sequence</Label>
                <p className="text-xs text-muted-foreground">The order in which Karen attempts engines when the active one fails. (Up to 4 steps)</p>
              </div>
              <div className="flex gap-2">
                <Button 
                  variant="outline"
                  size="sm"
                  className="h-8 text-[10px] font-bold uppercase tracking-widest border-primary/20 hover:bg-primary/5"
                  onClick={addSequenceStep}
                  disabled={!canManageRuntime || isSaving || fallbackOrder.length >= 4}
                >
                  Add Step
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  className="h-8 text-[10px] font-bold uppercase tracking-widest shadow-md"
                  onClick={() => handleSave(undefined, fallbackOrder)}
                  disabled={Boolean(!canManageRuntime || isSaving || (
                    exprSettings && 
                    JSON.stringify(exprSettings.fallback_order) === JSON.stringify(fallbackOrder) &&
                    exprSettings.active_engine === activeEngine
                  ))}
                >
                  {isSaving ? <Loader2 className="h-3 w-3 animate-spin mr-2" /> : <Save className="h-3 w-3 mr-2" />}
                  Save Expression
                </Button>

              </div>
            </div>

            <div className="space-y-3 max-w-2xl">
              {fallbackOrder.map((id, index) => {
                const isEnabled = exprSettings?.engines?.[id]?.enabled !== false;
                const Icon = getProviderIcon(id);
                
                return (
                  <div key={`${id}-${index}`} className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 text-primary border border-primary/20 text-xs font-mono font-bold shrink-0">
                      {index + 1}
                    </div>
                    
                    <div className={cn(
                      "flex-1 flex items-center justify-between rounded-xl border p-2 pl-4 transition-all",
                      isEnabled ? "bg-background border-border/60 shadow-sm" : "bg-muted/10 border-border/40 opacity-50 grayscale"
                    )}>
                      <div className="flex items-center gap-3 flex-1">
                        <Icon className="h-4 w-4 text-primary/60" />
                        <Select
                          value={id}
                          onValueChange={(val) => updateSequence(index, val)}
                        >
                          <SelectTrigger className="h-9 border-none bg-transparent font-bold uppercase tracking-tight text-xs p-0 focus:ring-0">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                             <SelectGroup>
                               <SelectLabel className="text-[9px] uppercase tracking-tighter opacity-50">Categories</SelectLabel>
                               <SelectItem value="builtin" className="text-[10px] font-bold">Built-In (Local)</SelectItem>
                               <SelectItem value="local" className="text-[10px] font-bold">Local AI (Server)</SelectItem>
                               <SelectItem value="cloud" className="text-[10px] font-bold">Cloud APIs (Remote)</SelectItem>
                             </SelectGroup>
                             
                             <SelectGroup>
                               <SelectLabel className="text-[9px] uppercase tracking-tighter opacity-50 border-t mt-1">Named Providers</SelectLabel>
                               {modelSettings?.providers?.map((provider) => (
                                 <SelectItem key={provider.id} value={provider.id} className="text-[10px] font-bold uppercase">{provider.display_name}</SelectItem>
                               ))}
                             </SelectGroup>
                             
                             <SelectItem value="none" className="text-destructive text-[10px] font-bold uppercase tracking-widest border-t">Remove Step</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      
                      {/* Show overrides if present */}
                      <div className="flex items-center gap-2 mr-3">
                         {asString(exprSettings?.engines?.[id]?.metadata?.preferred_model) && (
                            <Badge variant="outline" className="h-5 text-[7px] border-primary/20 bg-primary/5 text-primary">
                               MODEL: {asString(exprSettings?.engines?.[id]?.metadata?.preferred_model)}
                            </Badge>
                         )}
                         <Badge variant="secondary" className="h-5 text-[8px] bg-muted/40 font-mono text-muted-foreground shrink-0">
                           SLOT {index + 1}
                         </Badge>
                      </div>
                    </div>
                    
                    {index < 4 && (
                       <ArrowRight className="h-4 w-4 text-muted-foreground/30 shrink-0" />
                    )}
                  </div>
                );
              })}
              
              {/* Fixed 5th Step */}
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-destructive/10 text-destructive border border-destructive/20 text-xs font-mono font-bold shrink-0">
                  5
                </div>
                <div className="flex-1 flex items-center justify-between rounded-xl border border-dashed border-destructive/20 bg-destructive/[0.02] p-3 pl-4">
                  <div className="flex items-center gap-3">
                    <XCircle className="h-4 w-4 text-destructive" />
                    <span className="text-xs font-bold uppercase tracking-tight text-destructive">Emergency Static Endpoint</span>
                  </div>
                  <Badge variant="outline" className="h-5 text-[8px] border-destructive/20 text-destructive bg-destructive/5 uppercase font-bold shrink-0">
                    MANDATORY LAST RESORT
                  </Badge>
                </div>
              </div>
            </div>
            
            <div className="rounded-xl border bg-muted/5 p-4 max-w-2xl">
              <p className="text-[10px] text-muted-foreground leading-relaxed italic">
                <InfoIcon className="h-3 w-3 inline mr-1 mb-0.5" />
                Configure your engines to use specific models and providers above. Kari will automatically apply those preferences when traversing this sequence.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
