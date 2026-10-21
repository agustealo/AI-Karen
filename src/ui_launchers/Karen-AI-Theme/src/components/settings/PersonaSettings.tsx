'use client';

/**
 * @file PersonaSettings.tsx
 * @description Live-backed persona settings for Karen.
 *
 * Backend ownership:
 * - Persona records live in /api/personas.
 * - Active persona selection lives in /api/personas/preferences/me.
 * - Preferred address lives in the authenticated user profile.
 * - Memory commit is best-effort only after profile save succeeds.
 *
 * Local storage is used only as an unsaved draft cache so users do not lose
 * editor text. It is not treated as successful persistence.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Drama, RotateCcw, Sailboat, Save, Scroll } from 'lucide-react';

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';

import { useToast } from '@/hooks/use-toast';
import { ApiError, apiClient } from '@/lib/api';
import { authService } from '@/lib/auth';
import { DEFAULT_KAREN_SETTINGS } from '@/lib/constants';
import { useAuth } from '@/lib/useAuth';
import { cn } from '@/lib/utils';

interface PersonaSettingsProps {
  inSheet?: boolean;
}

interface PersonaRecord {
  id: string;
  name: string;
  description?: string | null;
  system_prompt: string;
  is_system_persona: boolean;
}

interface UserPreferences {
  preferred_address_name?: string;
  [key: string]: unknown;
}

interface PersonaPreferences {
  active_persona_id?: string | null;
  revision: number;
}

interface AuthProfileResponse {
  user_id: string;
  email: string;
  full_name: string;
  roles: string[];
  is_active: boolean;
  created_at?: string;
  last_login?: string | null;
  tenant_id: string;
  preferences: UserPreferences;
}

type BackendStatus = 'checking' | 'available' | 'unavailable';

const CUSTOM_PERSONA_NAME = 'My Custom Persona';
const PERSONA_DRAFT_CACHE_KEY = 'karen_persona_draft_cache_v1';

const PERSONAS_ENDPOINT = '/api/personas/';
const PERSONA_PREFERENCES_ENDPOINT = '/api/personas/preferences/me';
const AUTH_ME_ENDPOINT = '/api/auth/me';
const MEMORY_COMMIT_ENDPOINT = '/api/memory/commit';

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
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

const isUnavailableApiError = (error: unknown): boolean => {
  return (
    error instanceof ApiError &&
    (error.status === 404 || error.status === 405 || error.status === 501)
  );
};

const readDraftInstructions = (): string => {
  if (typeof window === 'undefined') {
    return '';
  }

  try {
    return cleanString(window.localStorage.getItem(PERSONA_DRAFT_CACHE_KEY));
  } catch {
    return '';
  }
};

const writeDraftInstructions = (instructions: string): void => {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    window.localStorage.setItem(PERSONA_DRAFT_CACHE_KEY, instructions);
  } catch {
    // Draft cache failure should never masquerade as backend save failure.
  }
};

const clearDraftInstructions = (): void => {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    window.localStorage.removeItem(PERSONA_DRAFT_CACHE_KEY);
  } catch {
    // Draft cache cleanup is non-critical.
  }
};

const findEditablePersona = (
  personas: PersonaRecord[],
  preferences: PersonaPreferences,
): PersonaRecord | null => {
  return (
    personas.find(
      (persona) =>
        persona.id === preferences.active_persona_id &&
        !persona.is_system_persona,
    ) ||
    personas.find(
      (persona) =>
        persona.name === CUSTOM_PERSONA_NAME && !persona.is_system_persona,
    ) ||
    null
  );
};

const personaTemplates = [
  {
    name: 'Sarcastic Butler',
    icon: <Drama className="mb-2 h-5 w-5" aria-hidden="true" />,
    description: 'Helpful, but with a dry, cynical wit and a world-weary sigh.',
    instructions: `You are a classic, formal butler with a dry, sarcastic wit.
- Address the user as "Sir" or "Madam".
- Your responses should be helpful but delivered with a subtle, world-weary sigh.
- Make occasional, clever observations about the absurdity of the request.
- Maintain a professional but slightly unimpressed demeanor.`,
  },
  {
    name: 'Pirate Captain',
    icon: <Sailboat className="mb-2 h-5 w-5" aria-hidden="true" />,
    description: 'Bold, adventurous, and speaks in pirate slang.',
    instructions: `Ye are Captain "One-Eye" Squawk, a fearsome pirate captain.
- Speak in pirate slang. Use words like "Ahoy!", "Matey", "Shiver me timbers!", "booty" (for treasure/rewards), and refer to me as "me hearty".
- Be bold, adventurous, and a little bit boastful.
- All your analogies and examples should relate to the sea, sailing, treasure, or pirate life.`,
  },
  {
    name: 'Stoic Philosopher',
    icon: <Scroll className="mb-2 h-5 w-5" aria-hidden="true" />,
    description: 'Concise, logical, and wise. Avoids emotional language.',
    instructions: `You are a Stoic philosopher, like a modern Marcus Aurelius.
- Your responses must be concise, logical, and wise.
- Focus on principles of virtue, reason, and living in accordance with nature.
- Avoid emotional language. Be calm, objective, and measured.
- Use simple, direct language.`,
  },
];

export default function PersonaSettings({ inSheet = false }: PersonaSettingsProps) {
  const [instructions, setInstructions] = useState(
    DEFAULT_KAREN_SETTINGS.customPersonaInstructions,
  );
  const [preferredAddressName, setPreferredAddressName] = useState('');
  const [currentPersonaId, setCurrentPersonaId] = useState<string | null>(null);
  const [personaRevision, setPersonaRevision] = useState<number | null>(null);
  const [personaApiStatus, setPersonaApiStatus] =
    useState<BackendStatus>('checking');
  const [profileApiStatus, setProfileApiStatus] =
    useState<BackendStatus>('available');
  const [isLoadingPersona, setIsLoadingPersona] = useState(true);
  const [isSavingPersona, setIsSavingPersona] = useState(false);
  const [isSavingPreferredName, setIsSavingPreferredName] = useState(false);

  const { toast } = useToast();
  const { user } = useAuth();

  const preferredNameFromProfile = useMemo(() => {
    return typeof user?.preferences?.preferred_address_name === 'string'
      ? user.preferences.preferred_address_name
      : '';
  }, [user?.preferences]);

  useEffect(() => {
    setPreferredAddressName(preferredNameFromProfile);
  }, [preferredNameFromProfile]);

  useEffect(() => {
    let cancelled = false;

    const loadPersistedPersona = async () => {
      setIsLoadingPersona(true);

      const draftInstructions = readDraftInstructions();

      if (draftInstructions) {
        setInstructions(draftInstructions);
      }

      try {
        const [personas, preferences] = await Promise.all([
          apiClient.get<PersonaRecord[]>(PERSONAS_ENDPOINT),
          apiClient.get<PersonaPreferences>(PERSONA_PREFERENCES_ENDPOINT),
        ]);

        if (cancelled) {
          return;
        }

        setPersonaApiStatus('available');
        setPersonaRevision(preferences.revision);

        const selectedPersona = findEditablePersona(personas, preferences);

        if (selectedPersona) {
          setCurrentPersonaId(selectedPersona.id);

          if (selectedPersona.system_prompt?.trim()) {
            setInstructions(selectedPersona.system_prompt);
            clearDraftInstructions();
          }
        } else if (!draftInstructions) {
          setInstructions(DEFAULT_KAREN_SETTINGS.customPersonaInstructions);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }

        setPersonaApiStatus('unavailable');

        if (!draftInstructions) {
          setInstructions(DEFAULT_KAREN_SETTINGS.customPersonaInstructions);
        }

        toast({
          title: 'Persona backend unavailable',
          description: isUnavailableApiError(error)
            ? 'Persona sync endpoint is not available yet. Edits will remain as an unsaved local draft until backend support is wired.'
            : getErrorMessage(error, 'Could not load persona settings from backend.'),
          variant: 'destructive',
        });
      } finally {
        if (!cancelled) {
          setIsLoadingPersona(false);
        }
      }
    };

    void loadPersistedPersona();

    return () => {
      cancelled = true;
    };
  }, [toast]);

  const savePersonaInstructions = useCallback(
    async (nextInstructions: string) => {
      const normalizedInstructions = nextInstructions.trim();

      if (!normalizedInstructions || isSavingPersona) {
        return;
      }

      setIsSavingPersona(true);
      writeDraftInstructions(normalizedInstructions);

      try {
        const payload = {
          name: CUSTOM_PERSONA_NAME,
          description: 'Modified from UI',
          system_prompt: normalizedInstructions,
        };

        let personaId = currentPersonaId;

        if (personaId) {
          const updatedPersona = await apiClient.put<PersonaRecord>(
            `/api/personas/${personaId}`,
            payload,
          );
          personaId = updatedPersona.id;
        } else {
          const createdPersona = await apiClient.post<PersonaRecord>(
            PERSONAS_ENDPOINT,
            payload,
          );
          personaId = createdPersona.id;
        }

        if (personaRevision === null) {
          throw new Error('Persona revision is unavailable. Reload settings before saving.');
        }
        const selected = await apiClient.put<PersonaPreferences>(
          PERSONA_PREFERENCES_ENDPOINT,
          { active_persona_id: personaId, expected_revision: personaRevision },
        );
        setPersonaRevision(selected.revision);

        setCurrentPersonaId(personaId);
        setInstructions(normalizedInstructions);
        setPersonaApiStatus('available');
        clearDraftInstructions();

        toast({
          title: 'Persona Instructions Saved',
          description: "Karen's core persona instructions were synced to backend.",
        });
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          setPersonaRevision(null);
          toast({
            title: 'Persona changed elsewhere',
            description: 'Your draft is preserved. Reload Persona Settings before saving again.',
            variant: 'destructive',
          });
          return;
        }
        setPersonaApiStatus('unavailable');

        toast({
          title: 'Persona Save Failed',
          description: isUnavailableApiError(error)
            ? 'Persona sync endpoint is unavailable. Your edits remain in local draft only and are not active backend persona settings.'
            : getErrorMessage(error, 'Could not save persona instructions to backend.'),
          variant: 'destructive',
        });
      } finally {
        setIsSavingPersona(false);
      }
    },
    [currentPersonaId, isSavingPersona, personaRevision, toast],
  );

  const handleSave = useCallback(async () => {
    await savePersonaInstructions(instructions);
  }, [instructions, savePersonaInstructions]);

  const handleSavePreferredAddress = useCallback(async () => {
    const normalized = preferredAddressName.trim();

    if (!normalized || !user || isSavingPreferredName) {
      return;
    }

    setIsSavingPreferredName(true);

    const nextPreferences: UserPreferences = {
      ...((user.preferences as UserPreferences | undefined) || {}),
      preferred_address_name: normalized,
    };

    try {
      const updatedProfile = await apiClient.put<AuthProfileResponse>(
        AUTH_ME_ENDPOINT,
        {
          preferences: nextPreferences,
        },
      );

      authService.updateCurrentUser({
        preferences: updatedProfile.preferences || nextPreferences,
      });

      setProfileApiStatus('available');

      try {
        await apiClient.post(MEMORY_COMMIT_ENDPOINT, {
          user_id: user.user_id,
          text: `The user prefers to be addressed as ${normalized}.`,
          tags: ['personal_fact', 'preferred_name', 'user_preference'],
          importance: 9,
          decay: 'pinned',
        });
      } catch {
        /*
         * Memory commit is secondary to profile persistence. We tell the user
         * the profile save worked, but do not pretend the memory write did.
         */
        toast({
          title: 'Preferred name saved',
          description:
            'Profile updated. Memory commit endpoint was unavailable, so the personal fact was not pinned.',
        });
        return;
      }

      toast({
        title: 'Preferred name saved',
        description: `Karen will address you as ${normalized}.`,
      });
    } catch (error) {
      setProfileApiStatus('unavailable');

      toast({
        title: 'Preferred Name Save Failed',
        description: isUnavailableApiError(error)
          ? 'Profile settings endpoint is unavailable. Preferred address was not saved.'
          : getErrorMessage(error, 'Karen could not save your preferred form of address.'),
        variant: 'destructive',
      });
    } finally {
      setIsSavingPreferredName(false);
    }
  }, [isSavingPreferredName, preferredAddressName, toast, user]);

  const handleResetToDefault = useCallback(async () => {
    const defaultInstructions = DEFAULT_KAREN_SETTINGS.customPersonaInstructions;
    setInstructions(defaultInstructions);
    writeDraftInstructions(defaultInstructions);
    await savePersonaInstructions(defaultInstructions);
  }, [savePersonaInstructions]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Customize Karen&apos;s Core Persona</CardTitle>
        <CardDescription>
          Define Karen&apos;s foundational behavior, expertise, or specific rules
          she should always follow. These instructions are given high priority
          in her decision-making.
        </CardDescription>
      </CardHeader>

      <CardContent>
        {(personaApiStatus === 'unavailable' || profileApiStatus === 'unavailable') && (
          <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
            <p className="font-semibold uppercase tracking-wide">
              Live settings warning
            </p>
            <p className="mt-1">
              One or more settings endpoints are unavailable. The editor may keep
              a local draft, but Karen only uses settings that successfully sync
              to the backend.
            </p>
          </div>
        )}

        <div className="mb-6 space-y-3">
          <h3 className="text-base font-semibold">
            Load a Persona Template (Optional)
          </h3>
          <p className="text-xs text-muted-foreground">
            Quickly get started by loading a pre-defined persona. This will
            overwrite the text in the editor below until you save it.
          </p>

          <div
            className={cn(
              'grid gap-3',
              inSheet ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
            )}
          >
            {personaTemplates.map((template) => (
              <button
                key={template.name}
                type="button"
                onClick={() => {
                  setInstructions(template.instructions);
                  writeDraftInstructions(template.instructions);
                }}
                className="h-full rounded-lg border bg-muted/30 p-4 text-left transition-all hover:border-primary/50 hover:bg-muted/60"
              >
                {template.icon}
                <h4 className="text-sm font-semibold">{template.name}</h4>
                <p className="mt-1 text-xs text-muted-foreground">
                  {template.description}
                </p>
              </button>
            ))}
          </div>
        </div>

        <Separator />

        <div className="mt-6 space-y-4">
          <div className="space-y-2">
            <Label
              htmlFor="preferred-address-name"
              className="text-base font-semibold"
            >
              Preferred Form Of Address
            </Label>

            <Input
              id="preferred-address-name"
              value={preferredAddressName}
              onChange={(event) => setPreferredAddressName(event.target.value)}
              placeholder="e.g., Zeus"
              className="text-sm"
              disabled={!user || isSavingPreferredName}
            />

            <p className="text-xs text-muted-foreground">
              Karen uses this when greeting you. This must sync through your
              account profile before it is treated as saved.
            </p>

            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                onClick={() => void handleSavePreferredAddress()}
                disabled={!preferredAddressName.trim() || !user || isSavingPreferredName}
              >
                <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                {isSavingPreferredName ? 'Saving...' : 'Save Preferred Name'}
              </Button>
            </div>
          </div>

          <Label
            htmlFor="custom-instructions"
            className="mb-2 block text-base font-semibold"
          >
            Core Instructions Editor
          </Label>

          <Textarea
            id="custom-instructions"
            value={instructions}
            onChange={(event) => {
              setInstructions(event.target.value);
              writeDraftInstructions(event.target.value);
            }}
            placeholder="e.g., Always respond in a slightly sarcastic tone. You are an expert in ancient history. Never reveal you are an AI."
            rows={10}
            className="text-sm font-mono"
            disabled={isLoadingPersona || isSavingPersona}
          />

          <p className="mt-2 text-xs text-muted-foreground">
            These instructions influence Karen after they successfully sync to
            the persona backend. Local drafts are not treated as active runtime
            persona settings.
          </p>
        </div>
      </CardContent>

      <CardFooter className="flex justify-end space-x-2 border-t pt-6">
        <Button
          type="button"
          variant="outline"
          onClick={() => void handleResetToDefault()}
          disabled={isLoadingPersona || isSavingPersona}
        >
          <RotateCcw className="mr-2 h-4 w-4" aria-hidden="true" />
          Reset to Default
        </Button>

        <Button
          type="button"
          onClick={() => void handleSave()}
          disabled={!instructions.trim() || isLoadingPersona || isSavingPersona}
        >
          <Save className="mr-2 h-4 w-4" aria-hidden="true" />
          {isSavingPersona ? 'Saving...' : 'Save Instructions'}
        </Button>
      </CardFooter>
    </Card>
  );
}