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
}

type SettingsSectionId =
  | 'behavior'
  | 'persona'
  | 'voice'
  | 'personal-facts'
  | 'notifications'
  | 'privacy'
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
}: SettingsDialogProps) {
  const categories = useMemo<SettingsCategory[]>(() => {
    const runtimeSections: SettingsSection[] = [
      {
        id: 'model',
        label: 'Providers',
        icon: Server,
        render: () => <ModelSettings />,
      },
      {
        id: 'expression',
        label: 'Expression',
        icon: Sparkles,
        render: () => <ExpressionSettings />,
      },
      {
        id: 'model-downloads',
        label: 'Model Downloads',
        icon: HardDrive,
        render: () => <ModelDownloads adminMode={adminMode} />,
      },
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
    useState<SettingsCategoryId>(DEFAULT_CATEGORY_ID);
  const [activeSectionId, setActiveSectionId] =
    useState<SettingsSectionId>('behavior');

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
    <div className={inSheet ? 'p-4' : 'space-y-8'}>
      {!inSheet && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <Cog className="h-6 w-6 text-primary" aria-hidden={true} />
            <h2 className="text-3xl font-bold tracking-tight text-foreground">
              Application Settings
            </h2>
          </div>

          <p className="karen-page-description">
            Fine-tune Karen&apos;s intelligence, manage your personal data, and
            configure system runtime parameters.
          </p>
        </div>
      )}

      {!inSheet && <Separator className="bg-border/40" />}

      <div className="space-y-6">
        <Tabs
          value={activeCategory?.id || DEFAULT_CATEGORY_ID}
          onValueChange={handleCategoryChange}
          className="w-full"
        >
          <TabsList
            className={[
              'grid h-auto w-full grid-cols-1 gap-2 rounded-2xl border border-border/40 bg-muted/30 p-1 text-foreground',
              adminMode
                ? 'sm:grid-cols-2 lg:w-[760px] lg:grid-cols-4'
                : 'sm:grid-cols-3 lg:w-[600px]',
            ].join(' ')}
          >
            {categories.map((category) => (
              <TabsTrigger
                key={category.id}
                value={category.id}
                className="rounded-xl border border-transparent px-4 py-2 text-sm font-semibold transition-all data-[state=active]:border-border/60 data-[state=active]:bg-background data-[state=active]:text-primary data-[state=active]:shadow-sm"
              >
                {category.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        {activeCategory && (
          <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div className="flex flex-col gap-3 rounded-2xl border border-border/40 bg-card/40 p-4 shadow-sm backdrop-blur-sm">
              <div className="flex items-center gap-2 px-1">
                <div className="h-1 w-1 rounded-full bg-primary" />
                <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/80">
                  {activeCategory.label} Configuration
                </span>
              </div>

              <div className="flex flex-wrap gap-2">
                {activeCategory.sections.map((section) => {
                  const Icon = section.icon;
                  const isActive = section.id === activeSectionId;

                  return (
                    <button
                      key={section.id}
                      type="button"
                      onClick={() => handleSectionChange(section.id)}
                      aria-pressed={isActive}
                      className={[
                        'inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium transition-all',
                        isActive
                          ? 'border-primary/40 bg-primary/10 text-primary shadow-sm'
                          : 'border-border/40 bg-muted/20 text-muted-foreground hover:border-border/80 hover:bg-muted/40 hover:text-foreground',
                      ].join(' ')}
                    >
                      <Icon className="h-4 w-4" aria-hidden={true} />
                      <span>{section.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <section className="min-w-0 space-y-6">
              {activeSection && (
                <div className="animate-in fade-in duration-500">
                  <div className="mb-4 flex items-center justify-between">
                    <div>
                      <h3 className="text-xl font-bold tracking-tight text-foreground">
                        {activeSection.label}
                      </h3>

                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground/70">
                        {activeCategory.label} &rsaquo; {activeSection.label}
                      </p>
                    </div>
                  </div>

                  <Separator className="mb-6 bg-border/40" />

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
