import type { Metadata } from 'next';
import './globals.css';
import { Toaster } from "@/components/ui/toaster";
import { ThemeProvider } from '@/providers/theme-provider';
import { PluginRegistryProvider } from '@/plugin_host/registry';
import { MessageInjectionProvider } from '@/providers/MessageInjectionProvider';
import SessionWarning from '@/components/SessionWarning';

const configuredPublicAppUrl =
  process.env.KAREN_APP_URL ??
  process.env.NEXT_PUBLIC_APP_URL ??
  process.env.APP_URL;

const metadataBase = configuredPublicAppUrl
  ? new URL(configuredPublicAppUrl)
  : undefined;

export const metadata: Metadata = {
  metadataBase,
  title: {
    default: 'KAREN | Local-first cognitive runtime',
    template: '%s | KAREN',
  },
  description:
    'KAREN is a local-first, prompt-first AI runtime for governed chat execution, durable memory, provider orchestration, agents, extensions, and observable automation.',
  applicationName: 'KAREN',
  manifest: '/manifest.webmanifest',
  icons: {
    icon: '/brand/karen-mark.svg',
    shortcut: '/brand/karen-mark.svg',
  },
  openGraph: {
    type: 'website',
    title: 'KAREN | Local-first cognitive runtime',
    description: 'Local by default. Governed by design.',
    images: [
      {
        url: '/brand/karen-banner.svg',
        width: 1600,
        height: 500,
        alt: 'KAREN, local by default and governed by design',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'KAREN | Local-first cognitive runtime',
    description: 'Local by default. Governed by design.',
    images: ['/brand/karen-banner.svg'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <ThemeProvider>
          <PluginRegistryProvider>
            <MessageInjectionProvider>
              <SessionWarning />
              {children}
              <Toaster />
            </MessageInjectionProvider>
          </PluginRegistryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
