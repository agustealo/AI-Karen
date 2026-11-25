import { defineConfig } from 'vitest/config';
import path from 'path';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    include: [
      'tests/**/*.test.{ts,tsx}',
      'src/realtime/tests/**/*.test.{ts,tsx}',
      'src/components/plugins/PluginOverviewPage.test.tsx',
      'src/components/plugins/FileExplorerInventoryHost.test.tsx',
      'src/components/comms/CommsCenterPage.test.tsx',
      'src/components/automation/AgentsPage.controlPlane.test.ts',
      'src/lib/card-studio-api.test.ts',
      'src/components/card-studio/CardStudioWorkspace.test.tsx',
    ],
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
  },
});
