"use client";

import { useAuth } from "@/lib/useAuth";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, ReactNode } from "react";

interface AuthWrapperProps {
  children: ReactNode;
}

export function AuthWrapper({ children }: AuthWrapperProps) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      const nextPath =
        pathname && pathname !== "/login" ? `?next=${encodeURIComponent(pathname)}` : "";
      const loginUrl = `/login${nextPath}`;
      router.replace(loginUrl);
    }
  }, [isAuthenticated, isLoading, pathname, router]);

  // Show loading spinner while checking authentication
  if (isLoading) {
    return (
      <div className="karen-app-shell karen-workspace-grid flex min-h-screen items-center justify-center bg-background">
        <div className="h-7 w-7 animate-spin rounded-full border-2 border-border border-t-primary" aria-label="Checking authentication" />
      </div>
    );
  }

  // If not authenticated, don't render children (will redirect)
  if (!isAuthenticated) {
    return (
      <div className="karen-app-shell karen-workspace-grid flex min-h-screen items-center justify-center bg-background text-muted-foreground">
        Redirecting to login...
      </div>
    );
  }

  // If authenticated, render children
  return <>{children}</>;
}
