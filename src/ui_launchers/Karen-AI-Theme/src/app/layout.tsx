
import type { Metadata } from 'next';
import './globals.css';
import { Toaster } from "@/components/ui/toaster";
import { ThemeProvider } from '@/providers/theme-provider';
import { PluginRegistryProvider } from '@/plugin_host/registry';
import { MessageInjectionProvider } from '@/providers/MessageInjectionProvider';
import SessionWarning from '@/components/SessionWarning';

export const metadata: Metadata = {
  title: 'Karen AI',
  description: 'Intelligent Assistant Application by Agustealo Studio',
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
