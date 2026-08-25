'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/lib/useAuth';
import { setupService } from '@/lib/setup';

export default function Home() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  useEffect(() => {
    if (isLoading) {
      return;
    }

    let cancelled = false;

    const resolveEntry = async () => {
      if (isAuthenticated) {
        router.replace('/dashboard');
        return;
      }

      try {
        const status = await setupService.getFirstRunStatus();
        if (!cancelled) {
          router.replace(status.first_run_required ? '/setup' : '/login');
        }
      } catch {
        if (!cancelled) {
          router.replace('/login?system=setup-status-unavailable');
        }
      }
    };

    void resolveEntry();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, isLoading, router]);

  return (
    <div className="flex h-screen w-full items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-3 text-sm text-muted-foreground">
        <Loader2 className="h-7 w-7 animate-spin" />
        <span>Checking Karen installation…</span>
      </div>
    </div>
  );
}
