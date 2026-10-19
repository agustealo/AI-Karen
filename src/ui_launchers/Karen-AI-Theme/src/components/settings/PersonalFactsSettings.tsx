'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bot,
  Brain,
  Calendar,
  Clock,
  FileText,
  Globe,
  Lightbulb,
  Lock,
  Mail,
  MessageSquare,
  MoreVertical,
  PlusCircle,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
  User,
  Zap,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { useToast } from '@/hooks/use-toast';
import { apiClient } from '@/lib/api';
import { cn } from '@/lib/utils';

type FactVisibility = 'private' | 'personal' | 'global';
type FactDomain = 'lifestyle' | 'professional' | 'business';

type FactSourceType =
  | 'manual'
  | 'gmail'
  | 'calendar'
  | 'chat'
  | 'manual_sync'
  | string;

type FactSuggestionStatus = 'accepted' | 'ignored';

type Fact = {
  id: string;
  text: string;
  visibility: FactVisibility;
  domain: FactDomain;
  category: string;
  importance: number;
  confidence: number;
  source?: string;
  sourceType?: FactSourceType;
  usage_count: number;
  created_at: string;
  last_used?: string | null;
};

type FactSuggestion = {
  id: string;
  text: string;
  confidence: number;
  reasoning: string;
  source: string;
};

type FactListResponse = {
  facts?: Fact[];
  items?: Fact[];
  data?: Fact[];
};

type FactSuggestionResponse = {
  suggestions?: FactSuggestion[];
  items?: FactSuggestion[];
  data?: FactSuggestion[];
};

type FactCreatePayload = {
  text: string;
  visibility: FactVisibility;
  domain: FactDomain;
  category: string;
  importance: number;
  confidence: number;
  source: string;
  sourceType: FactSourceType;
};

type ApiEndpointStatus = {
  factsAvailable: boolean;
  suggestionsAvailable: boolean;
  lastError: string;
};

const FACTS_ENDPOINT = '/api/memory/facts';
const FACT_SUGGESTIONS_ENDPOINT = '/api/memory/facts/suggestions';

const DEFAULT_CATEGORY = 'General';
const DEFAULT_VISIBILITY: FactVisibility = 'personal';
const DEFAULT_DOMAIN: FactDomain = 'lifestyle';

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const clamp01 = (value: unknown, fallback = 0): number => {
  const numeric = Number(value);

  if (!Number.isFinite(numeric)) {
    return fallback;
  }

  return Math.min(1, Math.max(0, numeric));
};

const normalizeVisibility = (value: unknown): FactVisibility => {
  const normalized = cleanString(value).toLowerCase();

  if (normalized === 'private' || normalized === 'personal' || normalized === 'global') {
    return normalized;
  }

  return DEFAULT_VISIBILITY;
};

const normalizeDomain = (value: unknown): FactDomain => {
  const normalized = cleanString(value).toLowerCase();

  if (
    normalized === 'lifestyle' ||
    normalized === 'professional' ||
    normalized === 'business'
  ) {
    return normalized;
  }

  return DEFAULT_DOMAIN;
};

const getErrorMessage = (
  error: unknown,
  fallback = 'Request failed.',
): string => {
  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }

  if (typeof error === 'string' && error.trim()) {
    return error.trim();
  }

  return fallback;
};

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
};

const normalizeFact = (value: unknown): Fact | null => {
  if (!isRecord(value)) {
    return null;
  }

  const id = cleanString(value.id || value.fact_id);
  const text = cleanString(value.text || value.content || value.value);

  if (!id || !text) {
    return null;
  }

  return {
    id,
    text,
    visibility: normalizeVisibility(value.visibility),
    domain: normalizeDomain(value.domain),
    category: cleanString(value.category) || DEFAULT_CATEGORY,
    importance: Number.isFinite(Number(value.importance))
      ? Number(value.importance)
      : 5,
    confidence: clamp01(value.confidence, 1),
    source: cleanString(value.source),
    sourceType: cleanString(value.sourceType || value.source_type || 'manual'),
    usage_count: Number.isFinite(Number(value.usage_count))
      ? Math.max(0, Number(value.usage_count))
      : 0,
    created_at:
      cleanString(value.created_at || value.createdAt),
    last_used: cleanString(value.last_used || value.lastUsed) || null,
  };
};

const normalizeSuggestion = (value: unknown): FactSuggestion | null => {
  if (!isRecord(value)) {
    return null;
  }

  const id = cleanString(value.id || value.suggestion_id);
  const text = cleanString(value.text || value.content || value.value);

  if (!id || !text) {
    return null;
  }

  return {
    id,
    text,
    confidence: clamp01(value.confidence, 0),
    reasoning: cleanString(value.reasoning || value.reason) || 'No reasoning supplied.',
    source: cleanString(value.source) || 'Karen memory analyzer',
  };
};

const extractFacts = (response: unknown): Fact[] => {
  if (Array.isArray(response)) {
    return response.map(normalizeFact).filter(Boolean) as Fact[];
  }

  if (!isRecord(response)) {
    return [];
  }

  const payload = response as FactListResponse;
  const rawFacts = payload.facts || payload.items || payload.data || [];

  return rawFacts.map(normalizeFact).filter(Boolean) as Fact[];
};

const extractSuggestions = (response: unknown): FactSuggestion[] => {
  if (Array.isArray(response)) {
    return response.map(normalizeSuggestion).filter(Boolean) as FactSuggestion[];
  }

  if (!isRecord(response)) {
    return [];
  }

  const payload = response as FactSuggestionResponse;
  const rawSuggestions =
    payload.suggestions || payload.items || payload.data || [];

  return rawSuggestions.map(normalizeSuggestion).filter(Boolean) as FactSuggestion[];
};

const getSafeDateLabel = (value: unknown): string => {
  const rawDate = cleanString(value);

  if (!rawDate) {
    return 'unknown';
  }

  const parsed = new Date(rawDate);

  if (Number.isNaN(parsed.getTime())) {
    return 'unknown';
  }

  return parsed.toLocaleDateString();
};

const getSourceIcon = (type: string | undefined) => {
  switch (type) {
    case 'gmail':
      return <Mail className="h-3 w-3" aria-hidden="true" />;
    case 'calendar':
      return <Calendar className="h-3 w-3" aria-hidden="true" />;
    case 'chat':
      return <MessageSquare className="h-3 w-3" aria-hidden="true" />;
    case 'manual_sync':
      return <Zap className="h-3 w-3" aria-hidden="true" />;
    default:
      return <FileText className="h-3 w-3" aria-hidden="true" />;
  }
};

const getVisibilityIcon = (visibility: FactVisibility) => {
  switch (visibility) {
    case 'private':
      return <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />;
    case 'personal':
      return <User className="h-3.5 w-3.5" aria-hidden="true" />;
    case 'global':
      return <Globe className="h-3.5 w-3.5" aria-hidden="true" />;
  }
};

export default function PersonalFactsSettings() {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [suggestions, setSuggestions] = useState<FactSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [processingSuggestionIds, setProcessingSuggestionIds] = useState<Record<string, boolean>>({});
  const [deletingFactIds, setDeletingFactIds] = useState<Record<string, boolean>>({});
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<'all' | FactVisibility>('all');
  const [domainFilter, setDomainFilter] = useState<'all' | FactDomain>('all');
  const [showSensitive, setShowSensitive] = useState<Record<string, boolean>>({});
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [factPendingDeletion, setFactPendingDeletion] = useState<Fact | null>(null);
  const [isSavingFact, setIsSavingFact] = useState(false);
  const [endpointStatus, setEndpointStatus] = useState<ApiEndpointStatus>({
    factsAvailable: true,
    suggestionsAvailable: true,
    lastError: '',
  });

  const { toast } = useToast();

  const [newFactText, setNewFactText] = useState('');
  const [newVisibility, setNewVisibility] =
    useState<FactVisibility>(DEFAULT_VISIBILITY);
  const [newDomain, setNewDomain] = useState<FactDomain>(DEFAULT_DOMAIN);
  const [newCategory, setNewCategory] = useState(DEFAULT_CATEGORY);

  const resetNewFactForm = useCallback(() => {
    setNewFactText('');
    setNewVisibility(DEFAULT_VISIBILITY);
    setNewDomain(DEFAULT_DOMAIN);
    setNewCategory(DEFAULT_CATEGORY);
  }, []);

  const loadFacts = useCallback(async (): Promise<Fact[]> => {
    const response = await apiClient.get<FactListResponse | Fact[]>(FACTS_ENDPOINT);
    return extractFacts(response);
  }, []);

  const loadSuggestions = useCallback(async (): Promise<FactSuggestion[]> => {
    const response = await apiClient.get<FactSuggestionResponse | FactSuggestion[]>(
      FACT_SUGGESTIONS_ENDPOINT,
    );
    return extractSuggestions(response);
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);

    /*
     * PersonalFactsSettings is live-backed. Facts and suggestions must come
     * from backend memory endpoints. Missing endpoints are shown honestly as
     * unavailable instead of silently falling back to synthetic memory.
     */
    const [factsResult, suggestionsResult] = await Promise.allSettled([
      loadFacts(),
      loadSuggestions(),
    ]);

    if (factsResult.status === 'fulfilled') {
      setFacts(factsResult.value);
      setEndpointStatus((current) => ({
        ...current,
        factsAvailable: true,
      }));
    } else {
      setFacts([]);
      setEndpointStatus((current) => ({
        ...current,
        factsAvailable: false,
        lastError: getErrorMessage(
          factsResult.reason,
          'Failed to load personal facts.',
        ),
      }));
    }

    if (suggestionsResult.status === 'fulfilled') {
      setSuggestions(suggestionsResult.value);
      setEndpointStatus((current) => ({
        ...current,
        suggestionsAvailable: true,
      }));
    } else {
      setSuggestions([]);
      setEndpointStatus((current) => ({
        ...current,
        suggestionsAvailable: false,
        lastError: getErrorMessage(
          suggestionsResult.reason,
          'Failed to load fact suggestions.',
        ),
      }));
    }

    setLoading(false);
  }, [loadFacts, loadSuggestions]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filteredFacts = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();

    return facts.filter((fact) => {
      const matchesSearch =
        !normalizedQuery ||
        fact.text.toLowerCase().includes(normalizedQuery) ||
        fact.category.toLowerCase().includes(normalizedQuery);

      const matchesVisibility =
        activeTab === 'all' ? true : fact.visibility === activeTab;

      const matchesDomain =
        domainFilter === 'all' ? true : fact.domain === domainFilter;

      return matchesSearch && matchesVisibility && matchesDomain;
    });
  }, [activeTab, domainFilter, facts, searchQuery]);

  const stats = useMemo(() => {
    const maturity = Math.round(
      (facts.reduce((acc, fact) => acc + fact.confidence, 0) /
        (facts.length || 1)) *
        100,
    );

    return {
      total: facts.length,
      private: facts.filter((fact) => fact.visibility === 'private').length,
      maturity,
    };
  }, [facts]);

  const handleAddFact = useCallback(async () => {
    const text = newFactText.trim();

    if (!text || isSavingFact) {
      return;
    }

    setIsSavingFact(true);

    try {
      const payload: FactCreatePayload = {
        text,
        visibility: newVisibility,
        domain: newDomain,
        category: newCategory.trim() || DEFAULT_CATEGORY,
        importance: 5,
        confidence: 1,
        source: 'Manual Entry',
        sourceType: 'manual',
      };

      await apiClient.post(FACTS_ENDPOINT, payload);
      resetNewFactForm();
      setIsAddDialogOpen(false);
      await loadData();

      toast({
        title: 'Memory Updated',
        description: 'Karen stored this fact in live long-term memory.',
      });
    } catch (error) {
      toast({
        title: 'Memory Save Failed',
        description: getErrorMessage(
          error,
          'Could not commit fact to long-term memory.',
        ),
        variant: 'destructive',
      });
    } finally {
      setIsSavingFact(false);
    }
  }, [
    isSavingFact,
    loadData,
    newCategory,
    newDomain,
    newFactText,
    newVisibility,
    resetNewFactForm,
    toast,
  ]);

  const handleProcessSuggestion = useCallback(
    async (id: string, status: FactSuggestionStatus) => {
      if (!id || processingSuggestionIds[id]) {
        return;
      }

      setProcessingSuggestionIds((current) => ({
        ...current,
        [id]: true,
      }));

      try {
        await apiClient.post(`${FACT_SUGGESTIONS_ENDPOINT}/${encodeURIComponent(id)}`, {
          status,
        });

        await loadData();

        toast({
          title: status === 'accepted' ? 'Fact Confirmed' : 'Suggestion Ignored',
          description:
            status === 'accepted'
              ? 'Insight was promoted to live memory.'
              : 'Karen will ignore this suggested memory pattern.',
        });
      } catch (error) {
        toast({
          title: 'Suggestion Update Failed',
          description: getErrorMessage(error, 'Failed to process suggestion.'),
          variant: 'destructive',
        });
      } finally {
        setProcessingSuggestionIds((current) => {
          const next = { ...current };
          delete next[id];
          return next;
        });
      }
    },
    [loadData, processingSuggestionIds, toast],
  );

  const handleDeleteFact = useCallback(
    async (id: string) => {
      if (!id || deletingFactIds[id]) {
        return;
      }

      setDeletingFactIds((current) => ({
        ...current,
        [id]: true,
      }));

      try {
        await apiClient.delete(`${FACTS_ENDPOINT}/${encodeURIComponent(id)}`);
        await loadData();
        setFactPendingDeletion(null);

        toast({
          title: 'Memory Deleted',
          description: 'The fact was removed from live memory.',
        });
      } catch (error) {
        toast({
          title: 'Delete Failed',
          description: getErrorMessage(error, 'Failed to delete fact.'),
          variant: 'destructive',
        });
      } finally {
        setDeletingFactIds((current) => {
          const next = { ...current };
          delete next[id];
          return next;
        });
      }
    },
    [deletingFactIds, loadData, toast],
  );

  const memoryUnavailable =
    !endpointStatus.factsAvailable || !endpointStatus.suggestionsAvailable;

  return (
    <div className="space-y-8 pb-10">
      {memoryUnavailable && (
        <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-700 dark:text-amber-300">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div>
              <p className="font-bold uppercase tracking-widest text-[10px]">
                Live memory endpoint warning
              </p>
              <p className="mt-1 text-xs">
                Some memory endpoints are unavailable. Karen is showing only live
                data that could be loaded. No synthetic facts are being used.
              </p>
              {endpointStatus.lastError && (
                <p className="mt-1 text-[10px] opacity-80">
                  {endpointStatus.lastError}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {[
          {
            label: 'Neural Footprint',
            value: stats.total,
            sub: 'Verified across all domains',
            icon: Brain,
            color: 'text-indigo-400',
          },
          {
            label: 'Secure Enclaves',
            value: stats.private,
            sub: 'Items in restricted state',
            icon: Lock,
            color: 'text-rose-400',
          },
          {
            label: 'Knowledge Maturity',
            value: `${stats.maturity}%`,
            sub: 'Average confidence index',
            icon: Target,
            color: 'text-emerald-400',
          },
        ].map((stat) => (
          <div
            key={stat.label}
            className="group flex items-center justify-between rounded-2xl border border-border/40 bg-card/30 p-5 backdrop-blur-sm transition-all hover:border-primary/20"
          >
            <div className="space-y-1">
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60">
                {stat.label}
              </p>
              <h4 className={cn('text-2xl font-black tracking-tighter', stat.color)}>
                {stat.value}
              </h4>
              <p className="text-[9px] font-medium uppercase tracking-tight text-muted-foreground/50">
                {stat.sub}
              </p>
            </div>
            <div className="rounded-xl border border-border/20 bg-background/50 p-3 transition-colors group-hover:bg-primary/5">
              <stat.icon className={cn('h-5 w-5', stat.color)} aria-hidden="true" />
            </div>
          </div>
        ))}
      </div>

      <Separator className="bg-border/20" />

      <div className="space-y-6">
        <div className="flex flex-col justify-between gap-6 lg:flex-row lg:items-center">
          <div className="space-y-1">
            <h3 className="text-xl font-bold tracking-tight">Memory Management</h3>
            <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground opacity-60">
              Personal Profile &rsaquo; Facts
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="group relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground transition-colors group-focus-within:text-primary" />
              <Input
                placeholder="Query knowledge base..."
                className="h-10 w-full rounded-xl border-border/40 bg-background/40 pl-10 text-xs font-bold uppercase tracking-tight sm:w-[280px]"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </div>

            <Button
              type="button"
              onClick={() => setIsAddDialogOpen(true)}
              size="sm"
              className="h-10 rounded-xl px-5 text-[10px] font-bold uppercase tracking-widest"
              disabled={!endpointStatus.factsAvailable}
            >
              <PlusCircle className="mr-2 h-4 w-4" aria-hidden="true" />
              Add Memory
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-4 border-y border-border/20 py-2 lg:flex-row lg:items-center">
          <div className="flex items-center gap-2">
            <span className="pl-2 text-[9px] font-black uppercase tracking-widest text-muted-foreground/60">
              Visibility:
            </span>
            <Tabs
              value={activeTab}
              onValueChange={(value) => setActiveTab(value as 'all' | FactVisibility)}
              className="w-auto"
            >
              <TabsList className="h-8 rounded-lg border border-border/10 bg-muted/40 p-1">
                <TabsTrigger value="all" className="h-6 px-3 text-[9px] font-bold uppercase">
                  All
                </TabsTrigger>
                <TabsTrigger value="personal" className="h-6 px-3 text-[9px] font-bold uppercase">
                  Personal
                </TabsTrigger>
                <TabsTrigger value="private" className="h-6 px-3 text-[9px] font-bold uppercase">
                  Private
                </TabsTrigger>
                <TabsTrigger value="global" className="h-6 px-3 text-[9px] font-bold uppercase">
                  Global
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <Separator orientation="vertical" className="hidden h-8 lg:block" />

          <div className="flex items-center gap-2">
            <span className="text-[9px] font-black uppercase tracking-widest text-muted-foreground/60">
              Domain:
            </span>
            <div className="flex gap-1.5">
              {(['all', 'lifestyle', 'professional', 'business'] as const).map((domain) => (
                <button
                  key={domain}
                  type="button"
                  onClick={() => setDomainFilter(domain)}
                  className={cn(
                    'rounded-lg border px-3 py-1 text-[9px] font-black uppercase transition-all',
                    domainFilter === domain
                      ? 'border-primary/30 bg-primary/10 text-primary'
                      : 'border-border/20 bg-transparent text-muted-foreground/40 hover:text-foreground',
                  )}
                  aria-pressed={domainFilter === domain}
                >
                  {domain}
                </button>
              ))}
            </div>
          </div>
        </div>

        <ScrollArea className="h-[500px] w-full rounded-2xl">
          {loading ? (
            <div
              className="flex h-[300px] flex-col items-center justify-center opacity-30"
              role="status"
              aria-live="polite"
            >
              <div className="mb-4 h-10 w-10 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <span className="text-[10px] font-black uppercase tracking-widest">
                Accessing live memory store...
              </span>
            </div>
          ) : filteredFacts.length > 0 ? (
            <div className="grid grid-cols-1 gap-4 pr-4">
              {filteredFacts.map((fact) => {
                const confidence = clamp01(fact.confidence, 0);
                const confidencePercent = Math.round(confidence * 100);
                const isDeleting = Boolean(deletingFactIds[fact.id]);

                return (
                  <div
                    key={fact.id}
                    className="group relative overflow-hidden rounded-2xl border border-border/40 bg-card/20 p-5 transition-all duration-500 hover:bg-card/40"
                  >
                    <div className="absolute right-0 top-0 p-4 opacity-5 transition-opacity group-hover:opacity-10">
                      <Brain className="h-12 w-12" aria-hidden="true" />
                    </div>

                    <div className="relative z-10 flex items-start justify-between">
                      <div className="flex-1 space-y-4">
                        <div className="flex flex-wrap items-center gap-4">
                          <Badge
                            variant="outline"
                            className="h-5 border-border/30 bg-background/50 px-2 text-[9px] font-black uppercase tracking-[0.1em]"
                          >
                            {getVisibilityIcon(fact.visibility)}
                            <span className="ml-1.5">{fact.visibility}</span>
                          </Badge>

                          <Badge
                            variant="outline"
                            className="h-5 border-primary/20 px-2 text-[9px] font-black uppercase tracking-[0.1em] text-primary/80"
                          >
                            {fact.domain}
                          </Badge>

                          <span className="text-[9px] font-bold uppercase tracking-[0.25em] text-zinc-600">
                            {fact.category}
                          </span>
                        </div>

                        <div className="relative">
                          {fact.visibility === 'private' && !showSensitive[fact.id] ? (
                            <button
                              type="button"
                              className="flex w-full items-center gap-3 rounded-xl border border-orange-500/10 bg-orange-500/5 p-4 text-left transition-all hover:bg-orange-500/10"
                              onClick={() =>
                                setShowSensitive((current) => ({
                                  ...current,
                                  [fact.id]: true,
                                }))
                              }
                            >
                              <Lock className="h-4 w-4 text-orange-500/60" aria-hidden="true" />
                              <span className="text-[11px] font-bold uppercase tracking-tighter text-muted-foreground/60 italic">
                                Sensitive record redacted. Reveal to view.
                              </span>
                            </button>
                          ) : (
                            <div className="space-y-3">
                              <p className="max-w-2xl text-base font-bold leading-relaxed tracking-tight text-foreground/90">
                                {fact.text}
                              </p>

                              <div className="flex flex-wrap items-center gap-6">
                                <div className="flex items-center gap-2">
                                  <div className="h-1 w-24 overflow-hidden rounded-full bg-zinc-900">
                                    <div
                                      className="h-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,0.5)]"
                                      style={{ width: `${confidencePercent}%` }}
                                    />
                                  </div>
                                  <span className="text-[9px] font-black uppercase text-indigo-400">
                                    {confidencePercent}% Match
                                  </span>
                                </div>

                                {fact.source && (
                                  <div className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-tight text-zinc-500 transition-colors hover:text-primary">
                                    {getSourceIcon(fact.sourceType)}
                                    <span>{fact.source}</span>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-col items-end gap-2">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 rounded-full border border-transparent transition-all hover:border-border/40 hover:bg-muted/50"
                              aria-label="Open fact actions"
                            >
                              <MoreVertical className="h-4 w-4" aria-hidden="true" />
                            </Button>
                          </DropdownMenuTrigger>

                          <DropdownMenuContent
                            align="end"
                            className="w-48 rounded-xl border-border/40 p-1"
                          >
                            <DropdownMenuItem
                              className="cursor-pointer rounded-lg text-[10px] font-bold uppercase tracking-widest text-rose-500 focus:text-rose-500"
                              onClick={() => setFactPendingDeletion(fact)}
                              disabled={isDeleting}
                            >
                              <Trash2 className="mr-2 h-3.5 w-3.5" aria-hidden="true" />
                              {isDeleting ? 'Purging...' : 'Purge Memory'}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>

                        <div className="mt-4 text-right">
                          <p className="text-[9px] font-black uppercase tracking-tighter text-zinc-600">
                            Usage Index
                          </p>
                          <p className="text-xs font-black text-foreground/40">
                            {fact.usage_count} hits
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="mt-6 flex items-center justify-between border-t border-border/10 pt-3 opacity-40 transition-opacity group-hover:opacity-80">
                      <span className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-widest">
                        <Clock className="h-3 w-3" aria-hidden="true" />
                        First Detected: {getSafeDateLabel(fact.created_at)}
                      </span>

                      {fact.last_used && (
                        <span className="text-[9px] font-black uppercase tracking-widest text-emerald-500 underline decoration-dotted">
                          Last context hit: {getSafeDateLabel(fact.last_used)}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex h-[300px] flex-col items-center justify-center rounded-[2.5rem] border-2 border-dashed border-border/20 bg-muted/5 opacity-40">
              <Sparkles className="mb-4 h-10 w-10 animate-pulse text-primary" aria-hidden="true" />
              <h4 className="text-lg font-black uppercase tracking-tighter">
                Null Knowledge State
              </h4>
              <p className="mt-1 text-center text-[10px] font-bold uppercase tracking-widest">
                Initialize the live neural store by committing facts manually or through plugins.
              </p>
            </div>
          )}
        </ScrollArea>
      </div>

      <Separator className="bg-border/20" />

      <div className="space-y-6">
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-3">
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-2 shadow-[0_0_15px_rgba(245,158,11,0.1)]">
              <Lightbulb className="h-5 w-5 text-amber-500" aria-hidden="true" />
            </div>
            <div>
              <h3 className="text-lg font-black uppercase tracking-[0.1em]">
                Pending Neural Curation
              </h3>
              <p className="text-[10px] font-bold uppercase tracking-tight text-muted-foreground/60 italic">
                AI extracted patterns awaiting user verification
              </p>
            </div>
          </div>

          <Badge
            variant="secondary"
            className="h-6 border-none bg-amber-500/10 px-3 font-black text-amber-500 animate-pulse"
          >
            {suggestions.length} NEW INSIGHTS
          </Badge>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {suggestions.map((suggestion) => {
            const isProcessing = Boolean(processingSuggestionIds[suggestion.id]);

            return (
              <div
                key={suggestion.id}
                className="group relative space-y-4 overflow-hidden rounded-[2rem] border border-primary/20 bg-gradient-to-br from-indigo-500/[0.04] to-transparent p-6"
              >
                <div className="absolute right-0 top-0 p-4 opacity-[0.03] transition-opacity group-hover:opacity-[0.08]">
                  <Target className="h-16 w-16 -rotate-45" aria-hidden="true" />
                </div>

                <div className="flex items-center justify-between pr-4">
                  <Badge className="h-5 border-none bg-primary/10 px-2 py-0 text-[9px] font-black tracking-widest text-primary">
                    PATTERN DETECTED
                  </Badge>
                  <span className="text-[9px] font-black uppercase tracking-widest text-indigo-400">
                    Confidence: {Math.round(clamp01(suggestion.confidence, 0) * 100)}%
                  </span>
                </div>

                <p className="text-base font-black leading-tight text-foreground/90">
                  &ldquo;{suggestion.text}&rdquo;
                </p>

                <div className="space-y-2 rounded-xl border border-white/5 bg-background/40 p-4">
                  <div className="flex items-center gap-1.5 text-[9px] font-black uppercase text-zinc-500">
                    <Bot className="h-3 w-3" aria-hidden="true" />
                    Karen&apos;s Reasoning
                  </div>
                  <p className="text-[10px] font-medium leading-relaxed text-muted-foreground/80 italic">
                    {suggestion.reasoning}
                  </p>
                </div>

                <div className="flex items-center justify-between pt-2">
                  <div className="flex items-center gap-2 text-[9px] font-bold uppercase text-zinc-600">
                    {getSourceIcon('chat')}
                    {suggestion.source}
                  </div>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() =>
                        void handleProcessSuggestion(suggestion.id, 'accepted')
                      }
                      className="h-8 rounded-lg bg-primary text-[10px] font-black uppercase tracking-widest transition-all hover:px-8"
                      disabled={isProcessing}
                    >
                      {isProcessing ? 'SYNCING...' : 'TRUST & SAVE'}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        void handleProcessSuggestion(suggestion.id, 'ignored')
                      }
                      className="h-8 rounded-lg text-[10px] font-black uppercase tracking-widest text-zinc-600 hover:text-rose-500"
                      disabled={isProcessing}
                    >
                      IGNORE
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}

          {suggestions.length === 0 && (
            <div className="col-span-full flex items-center justify-center rounded-[2rem] border border-dashed border-border/10 bg-muted/5 p-8 opacity-50">
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-zinc-600 italic">
                Continuous pattern monitoring active. No anomalies found.
              </p>
            </div>
          )}
        </div>
      </div>

      <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
        <DialogContent className="overflow-hidden rounded-[2.5rem] border-white/5 bg-[#0e0e0e] p-10 shadow-[0_0_50px_rgba(0,0,0,0.8)] sm:max-w-[500px]">
          <div className="absolute left-0 top-0 h-1 w-full bg-gradient-to-r from-indigo-500 to-purple-500" />
          <DialogHeader className="mb-6">
            <DialogTitle className="text-2xl font-black uppercase tracking-tighter">
              Initialize Memory Frame
            </DialogTitle>
            <DialogDescription className="text-xs font-bold uppercase tracking-widest text-muted-foreground opacity-50">
              Commit verified knowledge to the live long-term memory store
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6">
            <div className="space-y-2">
              <Label
                htmlFor="fact-text"
                className="ml-1 text-[10px] font-black uppercase tracking-[0.2em] text-zinc-600"
              >
                Knowledge Content
              </Label>
              <div className="group relative">
                <FileText className="absolute left-4 top-4 h-4 w-4 text-zinc-700 transition-colors group-focus-within:text-primary" aria-hidden="true" />
                <textarea
                  id="fact-text"
                  placeholder="e.g., Primary executive directive for Q2 is infrastructure scaling."
                  className="min-h-[100px] w-full resize-none rounded-2xl border border-white/10 bg-black py-4 pl-12 pr-4 text-sm font-bold transition-all placeholder:text-zinc-800 focus:outline-none focus:ring-1 focus:ring-primary/40"
                  value={newFactText}
                  onChange={(event) => setNewFactText(event.target.value)}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="ml-1 text-[10px] font-black uppercase tracking-[0.2em] text-zinc-600">
                  Visibility Level
                </Label>
                <Select
                  value={newVisibility}
                  onValueChange={(value) => setNewVisibility(value as FactVisibility)}
                >
                  <SelectTrigger className="h-12 rounded-xl border border-white/10 bg-black text-[10px] font-bold uppercase tracking-widest">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="overflow-hidden rounded-xl border-white/10 bg-black shadow-2xl">
                    <SelectItem value="personal">
                      <span className="text-[10px] font-black uppercase">
                        Personal Profile
                      </span>
                    </SelectItem>
                    <SelectItem value="private">
                      <span className="text-[10px] font-black uppercase">
                        Private Enclave
                      </span>
                    </SelectItem>
                    <SelectItem value="global">
                      <span className="text-[10px] font-black uppercase">
                        Global Shared
                      </span>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="ml-1 text-[10px] font-black uppercase tracking-[0.2em] text-zinc-600">
                  Context Domain
                </Label>
                <Select
                  value={newDomain}
                  onValueChange={(value) => setNewDomain(value as FactDomain)}
                >
                  <SelectTrigger className="h-12 rounded-xl border border-white/10 bg-black text-[10px] font-bold uppercase tracking-widest">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="overflow-hidden rounded-xl border-white/10 bg-black shadow-2xl">
                    <SelectItem value="lifestyle">
                      <span className="text-[10px] font-black uppercase">
                        Lifestyle Core
                      </span>
                    </SelectItem>
                    <SelectItem value="professional">
                      <span className="text-[10px] font-black uppercase">
                        Professional Hub
                      </span>
                    </SelectItem>
                    <SelectItem value="business">
                      <span className="text-[10px] font-black uppercase">
                        Business Matrix
                      </span>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label className="ml-1 text-[10px] font-black uppercase tracking-[0.2em] text-zinc-600">
                Semantic Category
              </Label>
              <div className="group relative">
                <Target className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-700" aria-hidden="true" />
                <Input
                  placeholder="e.g., Working Style, Preference, Strategy"
                  className="h-12 rounded-xl border border-white/10 bg-black pl-12 text-[10px] font-bold uppercase tracking-widest"
                  value={newCategory}
                  onChange={(event) => setNewCategory(event.target.value)}
                />
              </div>
            </div>
          </div>

          <DialogFooter className="flex flex-col gap-3 pt-10 sm:flex-row">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setIsAddDialogOpen(false)}
              className="h-12 flex-1 text-[10px] font-black uppercase tracking-[0.25em] text-zinc-500 hover:bg-white/5"
              disabled={isSavingFact}
            >
              ABORT
            </Button>
            <Button
              type="button"
              onClick={() => void handleAddFact()}
              className="h-12 flex-1 bg-indigo-600 text-[10px] font-black uppercase tracking-[0.25em] shadow-[0_10px_30px_-5px_rgba(79,70,229,0.5)] hover:bg-indigo-500"
              disabled={!newFactText.trim() || isSavingFact}
            >
              {isSavingFact ? 'SYNCING...' : 'INITIALIZE SYNC'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(factPendingDeletion)} onOpenChange={(open) => { if (!open && !deletingFactIds[factPendingDeletion?.id || '']) setFactPendingDeletion(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete saved fact?</DialogTitle>
            <DialogDescription>
              This requests deletion from Karen&apos;s live memory. Other retained records may be governed by separate retention rules.
            </DialogDescription>
          </DialogHeader>
          <p className="max-h-36 overflow-auto rounded-lg border border-border/50 bg-muted/30 p-3 text-sm">{factPendingDeletion?.text}</p>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setFactPendingDeletion(null)} disabled={Boolean(factPendingDeletion && deletingFactIds[factPendingDeletion.id])}>Cancel</Button>
            <Button type="button" variant="destructive" disabled={!factPendingDeletion || Boolean(deletingFactIds[factPendingDeletion.id])} onClick={() => { if (factPendingDeletion) void handleDeleteFact(factPendingDeletion.id); }}>
              {factPendingDeletion && deletingFactIds[factPendingDeletion.id] ? 'Deleting…' : 'Confirm deletion'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}