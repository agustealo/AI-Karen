"use client";

import { useAuth } from "@/lib/useAuth";
import { usePathname, useRouter } from "next/navigation";
import { Fragment, useEffect, ReactNode } from "react";

interface AuthWrapperProps {
  children: ReactNode;
}

export function AuthWrapper({ children }: AuthWrapperProps) {
  const { isAuthenticated, isLoading, user } = useAuth();
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

  // An authenticated boolean is not an identity boundary. Refresh/login can
  // replace the principal without a transient unauthenticated render. Do not
  // expose the previous user's mounted chat, drafts or session state.
  if (!user?.user_id?.trim() || !user?.tenant_id?.trim()) {
    return (
      <div role="status" className="karen-app-shell flex min-h-screen items-center justify-center bg-background text-muted-foreground">
        Verifying account identity...
      </div>
    );
  }

  // Remount all owned state whenever tenant OR user changes. JSON tuple
  // encoding avoids collisions between principal IDs containing separators.
  const principalKey = JSON.stringify([user.tenant_id, user.user_id]);
  return <Fragment key={principalKey}>{children}</Fragment>;
}
