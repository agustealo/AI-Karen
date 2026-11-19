'use client';

/**
 * @file SettingsDialog.tsx
 * @description Settings shell for Karen UI.
 *
 * Shell boundary:
 * - This component owns navigation between settings panels only.
 * - Individual panels own their own live backend reads/writes.
 * - Do not add persistence, provider routing, localStorage writes, or backend
 *   setting mutations here.
 */

import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Bell,
  BookText,
  Cog,
  GraduationCap,
  HardDrive,
  MessageSquareMore,
  MessagesSquare,
  Shield,
  Speaker,
  UserCog,
  Zap,
  Server,
  Sparkles,
  type LucideIcon,
} from 'lucide-react';

import { Separator } from '@/components/ui/separator';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

import TrainingSettingsPanel from '@/components/admin/TrainingSettingsPanel';
import CommsCenterPage from '@/components/comms/CommsCenterPage';

import BehaviorSettings from './BehaviorSettings';
import ChannelsSettings from './ChannelsSettings';
import WhatsAppCloudSettings from './WhatsAppCloudSettings';
import ModelDownloads from './ModelDownloads';
import ModelSettings from './ModelSettings';
import ExpressionSettings from './ExpressionSettings';
import NotificationSettings from './NotificationSettings';
import OptimizationSettings from './OptimizationSettings';
import PersonaSettings from './PersonaSettings';
import PersonalFactsSettings from './PersonalFactsSettings';
import PrivacySettings from './PrivacySettings';
import VoiceSettings from './VoiceSettings';

interface SettingsDialogProps {
  inSheet?: boolean;
  adminMode?: boolean;
  /** Optional consumer navigation target; the panel still owns its reads/writes. */
  initialSection?: 'behavior' | 'model' | 'voice';
}

type SettingsSectionId =
  | 'behavior'
  | 'persona'
  | 'voice'
  | 'personal-facts'
  | 'notifications'
  | 'privacy'
  | 'channels'
  | 'whatsapp-cloud'
  | 'model'
  | 'expression'
  | 'model-downloads'
  | 'optimization'
  | 'training'
  | 'communications';

type SettingsCategoryId = 'assistant' | 'personal' | 'runtime' | 'admin';

type SettingsSection = {
  id: SettingsSectionId;
  label: string;
  description?: string;
  icon: LucideIcon;
  render: () => ReactNode;
};

type SettingsCategory = {
  id: SettingsCategoryId;
  label: string;
  sections: SettingsSection[];
};

const DEFAULT_CATEGORY_ID: SettingsCategoryId = 'assistant';

const isSectionInCategory = (
  category: SettingsCategory | undefined,
  sectionId: string,
): boolean => {
  return Boolean(category?.sections.some((section) => section.id === sectionId));
};

const findSectionById = (
  categories: SettingsCategory[],
  sectionId: string,
): SettingsSection | undefined => {
  return categories
    .flatMap((category) => category.sections)
    .find((section) => section.id === sectionId);
};

const findCategoryBySectionId = (
  categories: SettingsCategory[],
  sectionId: string,
): SettingsCategory | undefined => {
  return categories.find((category) =>
    category.sections.some((section) => section.id === sectionId),
  );
};

export default function SettingsDialog({
  inSheet = false,
  adminMode = false,
  initialSection = 'behavior',
}: SettingsDialogProps) {
  const categories = useMemo<SettingsCategory[]>(() => {
    const runtimeSections: SettingsSection[] = [
      {
        id: 'model',
        label: 'Providers',
        description: 'Choose a connected model provider, inspect available models, and configure its runtime connection.',
        icon: Server,
        render: () => <ModelSettings />,
      },
      {
        id: 'expression',
        label: 'Expression',
        description: 'Review how Karen routes reasoning and responses between configured engines and fallbacks.',
        icon: Sparkles,
        render: () => <ExpressionSettings />,
      },
      ...(adminMode ? [{
        id: 'model-downloads' as const,
        label: 'Model Downloads',
        description: 'Administer local model downloads, installed inventory, and download jobs.',
        icon: HardDrive,
        render: () => <ModelDownloads adminMode={adminMode} />,
      }] : []),
    ];

    if (adminMode) {
      runtimeSections.push({
        id: 'optimization',
        label: 'Acceleration',
        icon: Zap,
        render: () => <OptimizationSettings />,
      });
    }

    const nextCategories: SettingsCategory[] = [
      {
        id: 'assistant',
        label: 'Assistant',
        sections: [
          {
            id: 'behavior',
            label: 'Behavior',
            icon: Cog,
            render: () => <BehaviorSettings />,
          },
          {
            id: 'persona',
            label: 'Persona',
            icon: UserCog,
            render: () => <PersonaSettings inSheet={inSheet} />,
          },
          {
            id: 'voice',
            label: 'Voice',
            icon: Speaker,
            render: () => <VoiceSettings />,
          },
        ],
      },
      {
        id: 'personal',
        label: 'Personal',
        sections: [
          {
            id: 'personal-facts',
            label: 'Facts',
            icon: BookText,
            render: () => <PersonalFactsSettings />,
          },
          {
            id: 'notifications',
            label: 'Alerts',
            icon: Bell,
            render: () => <NotificationSettings />,
          },
          {
            id: 'privacy',
            label: 'Privacy',
            icon: Shield,
            render: () => <PrivacySettings />,
          },
          {
            id: 'channels',
            label: 'Channels',
            description: 'View verified, account-owned channel status without claiming live pairing.',
            icon: MessagesSquare,
            render: () => <ChannelsSettings />,
          },
        ],
      },
      {
        id: 'runtime',
        label: 'Models & Runtime',
        sections: runtimeSections,
      },
    ];

    if (adminMode) {
      nextCategories.push({
        id: 'admin',
        label: 'Admin',
        sections: [
          {
            id: 'whatsapp-cloud',
            label: 'WhatsApp Cloud',
            description: 'Governed Meta WhatsApp Cloud account provisioning and local lifecycle, with explicit verification status.',
            icon: MessagesSquare,
            render: () => <WhatsAppCloudSettings />,
          },
          {
            id: 'training',
            label: 'Training',
            icon: GraduationCap,
            render: () => <TrainingSettingsPanel />,
          },
          {
            id: 'communications',
            label: 'Communications',
            icon: MessageSquareMore,
            render: () => <CommsCenterPage />,
          },
        ],
      });
    }

    return nextCategories;
  }, [adminMode, inSheet]);

  const allSections = useMemo(
    () => categories.flatMap((category) => category.sections),
    [categories],
  );

  const [activeCategoryId, setActiveCategoryId] =
    useState<SettingsCategoryId>(initialSection === 'model' ? 'runtime' : DEFAULT_CATEGORY_ID);
  const [activeSectionId, setActiveSectionId] =
    useState<SettingsSectionId>(initialSection);

  useEffect(() => {
    // Navigation handoff only. Provider configuration and persistence remain
    // exclusively owned by the existing ModelSettings panel and backend.
    setActiveCategoryId(initialSection === 'model' ? 'runtime' : DEFAULT_CATEGORY_ID);
    setActiveSectionId(initialSection);
  }, [initialSection]);

  const activeCategory = useMemo(() => {
    return (
      categories.find((category) => category.id === activeCategoryId) ||
      categories[0]
    );
  }, [activeCategoryId, categories]);

  const activeSection = useMemo(() => {
    return (
      findSectionById(categories, activeSectionId) ||
      activeCategory?.sections[0] ||
      allSections[0]
    );
  }, [activeCategory, activeSectionId, allSections, categories]);

  useEffect(() => {
    /*
     * Keep navigation valid when adminMode or inSheet changes the available
     * category/section tree. Settings panels own persistence; this shell only
     * prevents dead navigation state.
     */
    const categoryExists = categories.some(
      (category) => category.id === activeCategoryId,
    );

    if (!categoryExists) {
      const fallbackCategory = categories[0];
      setActiveCategoryId(fallbackCategory?.id || DEFAULT_CATEGORY_ID);
      setActiveSectionId(fallbackCategory?.sections[0]?.id || 'behavior');
      return;
    }

    const currentCategory = categories.find(
      (category) => category.id === activeCategoryId,
    );

    if (!isSectionInCategory(currentCategory, activeSectionId)) {
      setActiveSectionId(currentCategory?.sections[0]?.id || 'behavior');
    }
  }, [activeCategoryId, activeSectionId, categories]);

  const handleCategoryChange = (categoryId: string) => {
    const nextCategory = categories.find(
      (category) => category.id === categoryId,
    );

    if (!nextCategory) {
      return;
    }

    setActiveCategoryId(nextCategory.id);

    if (!isSectionInCategory(nextCategory, activeSectionId)) {
      setActiveSectionId(nextCategory.sections[0]?.id || activeSectionId);
    }
  };

  const handleSectionChange = (sectionId: SettingsSectionId) => {
    const owningCategory = findCategoryBySectionId(categories, sectionId);

    if (owningCategory && owningCategory.id !== activeCategoryId) {
      setActiveCategoryId(owningCategory.id);
    }

    setActiveSectionId(sectionId);
  };

  return (
    <div data-kari-root data-testid="karen-settings-workspace" className={inSheet ? 'karen-settings min-w-0 space-y-5 p-4 sm:p-5' : 'karen-settings min-w-0 space-y-6 pb-8'}>
      {!inSheet && (
        <header className="karen-settings-hero karen-surface relative isolate overflow-hidden rounded-2xl p-5 sm:p-8">
          <div className="relative z-10 flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 max-w-2xl space-y-3">
              <p className="karen-metric uppercase tracking-[0.16em] text-primary">
                KARI OS / WORKSPACE CONFIGURATION
              </p>
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-primary/25 bg-primary/10 text-primary" aria-hidden="true">
                  <Cog className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="karen-page-title kari-display text-balance">Application Settings</h2>
                  <p className="karen-page-description mt-2">
                    Fine-tune Karen&apos;s intelligence, manage your personal data, and
                    configure system runtime parameters.
                  </p>
                </div>
              </div>
            </div>
            <div className="karen-settings-authority rounded-xl border border-border/70 bg-card/65 px-4 py-3">
              <p className="karen-metric uppercase text-muted-foreground">Configuration authority</p>
              <p className="mt-1 flex items-center gap-2 text-xs font-medium text-foreground">
                <Shield className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                Backend-owned settings
              </p>
            </div>
          </div>
        </header>
      )}

      <div className="min-w-0 space-y-5">
        <Tabs
          value={activeCategory?.id || DEFAULT_CATEGORY_ID}
          onValueChange={handleCategoryChange}
          className="w-full"
        >
          <TabsList
            className={[
              'karen-settings-categories grid h-auto w-full grid-cols-1 gap-1 rounded-xl border border-border/70 bg-card/80 p-1.5 text-foreground',
              adminMode
                ? 'sm:grid-cols-2 lg:max-w-[780px] lg:grid-cols-4'
                : 'sm:grid-cols-3 lg:max-w-[660px]',
            ].join(' ')}
          >
            {categories.map((category) => (
              <TabsTrigger
                key={category.id}
                value={category.id}
                className="min-h-11 rounded-lg border border-transparent px-4 py-2.5 text-sm font-semibold transition-colors data-[state=active]:border-primary/30 data-[state=active]:bg-primary/10 data-[state=active]:text-primary"
              >
                {category.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        {activeCategory && (
          <div className="grid min-w-0 gap-5 lg:grid-cols-[240px_minmax(0,1fr)] lg:items-start">
            <div className="karen-settings-section-nav karen-surface flex min-w-0 flex-col gap-4 rounded-xl p-4 lg:sticky lg:top-4">
              <div className="flex items-center gap-2 px-1">
                <div className="h-1 w-1 rounded-full bg-primary" />
                <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/80">
                  {activeCategory.label} Configuration
                </span>
              </div>

              <p className="px-1 text-sm text-muted-foreground">
                {activeCategory.id === 'runtime'
                  ? 'Available providers, routing controls, and saved settings are reported by Karen. Changes are only applied when the backend confirms them.'
                  : activeCategory.id === 'personal'
                    ? 'Review personal information, notifications, and privacy controls.'
                    : activeCategory.id === 'assistant'
                      ? 'Customize how Karen behaves, speaks, and presents itself.'
                      : 'Manage authorized administration controls.'}
              </p>
              <nav aria-label={`${activeCategory.label} settings sections`} className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-1">
                {activeCategory.sections.map((section) => {
                  const Icon = section.icon;
                  const isActive = section.id === activeSectionId;

                  return (
                    <button
                      key={section.id}
                      type="button"
                      onClick={() => handleSectionChange(section.id)}
                      aria-current={isActive ? 'page' : undefined}
                      aria-controls="settings-active-panel"
                      title={section.description || section.label}
                      className={[
                        'inline-flex min-h-11 min-w-0 items-center gap-3 rounded-lg border px-3 py-2 text-left text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
                        isActive
                          ? 'border-primary/40 bg-primary/10 text-primary'
                          : 'border-transparent bg-transparent text-muted-foreground hover:border-border/70 hover:bg-muted/30 hover:text-foreground',
                      ].join(' ')}
                    >
                      <Icon className="h-4 w-4" aria-hidden={true} />
                      <span className="min-w-0 truncate">{section.label}</span>
                    </button>
                  );
                })}
              </nav>
            </div>

            <section id="settings-active-panel" aria-label={activeSection?.label || 'Settings'} className="karen-settings-active min-w-0 space-y-5">
              {activeSection && (
                <div className="min-w-0">
                  <div className="karen-settings-panel-heading mb-5 flex min-w-0 items-start justify-between gap-4 rounded-xl border border-border/70 bg-card/80 p-5 sm:p-6">
                    <div>
                      <h3 className="kari-display text-xl font-bold tracking-tight text-foreground sm:text-2xl">
                        {activeSection.label}
                      </h3>

                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground/70">
                        {activeCategory.label} &rsaquo; {activeSection.label}
                      </p>
                      {activeSection.description && (
                        <p className="mt-2 max-w-2xl text-sm font-normal normal-case tracking-normal text-muted-foreground">
                          {activeSection.description}
                        </p>
                      )}
                    </div>
                  </div>

                  <Separator className="mb-5 bg-border/40" />

                  <div className="rounded-xl">{activeSection.render()}</div>
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
