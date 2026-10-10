import ManualFreePluginCatalog from '@/components/plugins/ManualFreePluginCatalog';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Free Plugins | Karen AI',
  description: 'Browse essential and premium plugins for manual installation',
};

export default function PluginsPage() {
  return <ManualFreePluginCatalog />;
}
