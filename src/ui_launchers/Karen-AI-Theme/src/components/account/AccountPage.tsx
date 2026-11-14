"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2, Eye, EyeOff, Lock, LogOut, Mail, Monitor, Moon,
  RefreshCw, Save, ShieldCheck, Sun, User, UserRound,
} from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { apiClient } from "@/lib/api";
import { authService } from "@/lib/auth";
import { useAuth } from "@/lib/useAuth";
import { useTheme, type Theme } from "@/providers/theme-provider";

type UserPreferences = Record<string, unknown> & { theme?: Theme };
type AccountUser = {
  user_id: string;
  tenant_id: string;
  username: string;
  full_name: string;
  email: string;
  roles: string[];
  is_active: boolean;
  created_at: string;
  last_login: string | null;
  preferences: UserPreferences;
  avatarUrl?: string;
};
type AccountPrincipal = { user_id: string; tenant_id: string };

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark" || value === "system";
}

function verifyAccount(payload: unknown, principal: AccountPrincipal): AccountUser {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Karen returned an invalid account record. Refresh to retry.");
  }
  const record = payload as Record<string, unknown>;
  if (
    record.user_id !== principal.user_id ||
    record.tenant_id !== principal.tenant_id ||
    record.is_active !== true ||
    typeof record.email !== "string" ||
    typeof record.username !== "string" ||
    typeof record.full_name !== "string" ||
    !Array.isArray(record.roles) ||
    !record.roles.every((role) => typeof role === "string") ||
    typeof record.created_at !== "string" ||
    (record.last_login !== null && record.last_login !== undefined && typeof record.last_login !== "string") ||
    !record.preferences ||
    typeof record.preferences !== "object" ||
    Array.isArray(record.preferences)
  ) {
    throw new Error("Karen could not verify this account's identity or saved details.");
  }
  return {
    user_id: record.user_id,
    tenant_id: record.tenant_id,
    email: record.email,
    username: record.username,
    full_name: record.full_name,
    roles: record.roles as string[],
    is_active: record.is_active,
    created_at: record.created_at,
    last_login: typeof record.last_login === "string" ? record.last_login : null,
    preferences: record.preferences as UserPreferences,
    avatarUrl: typeof record.avatarUrl === "string" ? record.avatarUrl : undefined,
  };
}

function getInitials(value: string): string {
  const parts = value.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "KA";
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function formatDate(value: string | null): string {
  if (!value) return "Not available";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Not available" : date.toLocaleString();
}

function readableRoles(roles: string[]): string {
  if (!roles.length) return "Member";
  return roles.map((role) => role.replace(/_/g, " "))
    .map((role) => role.charAt(0).toUpperCase() + role.slice(1)).join(", ");
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

export default function AccountPage() {
  const router = useRouter();
  const { toast } = useToast();
  const { user: signedInUser, isAuthenticated, isLoading: authLoading, logout } = useAuth();
  const { theme, setTheme } = useTheme();

  const userId = signedInUser?.user_id ?? "";
  const tenantId = signedInUser?.tenant_id ?? "";
  const principal = useMemo<AccountPrincipal | null>(
    () => isAuthenticated && userId && tenantId ? { user_id: userId, tenant_id: tenantId } : null,
    [isAuthenticated, userId, tenantId],
  );

  const [account, setAccount] = useState<AccountUser | null>(null);
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isProfileSaving, setIsProfileSaving] = useState(false);
  const [pendingTheme, setPendingTheme] = useState<Theme | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [isPasswordSaving, setIsPasswordSaving] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const loadVersion = useRef(0);

  const applyAccount = useCallback((verified: AccountUser) => {
    setAccount(verified);
    setUsername(verified.username);
    setFullName(verified.full_name);
    setEmail(verified.email);
    // AuthProvider and the theme provider observe the canonical owned user
    // event. Preserve existing permissions while updating account-owned fields.
    authService.updateCurrentUser({
      username: verified.username,
      email: verified.email,
      full_name: verified.full_name,
      preferences: verified.preferences,
    });
  }, []);

  const loadProfile = useCallback(async (announce = false) => {
    const version = ++loadVersion.current;
    if (!principal) {
      setAccount(null);
      setLoadError("Sign in to access your account details.");
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setLoadError(null);
    try {
      const result = await apiClient.get<unknown>("/api/auth/me");
      const verified = verifyAccount(result, principal);
      if (loadVersion.current !== version) return;
      applyAccount(verified);
      if (announce) {
        toast({ title: "Profile refreshed", description: "Your current account details were loaded from Karen." });
      }
    } catch (error) {
      if (loadVersion.current !== version) return;
      setAccount(null);
      setLoadError(errorMessage(error, "Your account could not be loaded."));
    } finally {
      if (loadVersion.current === version) setIsLoading(false);
    }
  }, [applyAccount, principal, toast]);

  useEffect(() => {
    void loadProfile();
    return () => { loadVersion.current += 1; };
  }, [loadProfile]);

  const cleanUsername = username.trim();
  const cleanName = fullName.trim();
  const cleanEmail = email.trim().toLowerCase();
  const profileError =
    !cleanUsername || cleanUsername.length > 64 || /\s/.test(cleanUsername)
      ? "Enter a username without spaces (maximum 64 characters)."
      : !cleanName || cleanName.length > 128
        ? "Enter your display name (maximum 128 characters)."
        : cleanEmail.length > 254 || !EMAIL_PATTERN.test(cleanEmail)
          ? "Enter a valid email address."
          : null;
  const profileDirty = !!account && (
    cleanUsername !== account.username ||
    cleanName !== account.full_name ||
    cleanEmail !== account.email.toLowerCase()
  );
  const isMutating = isProfileSaving || pendingTheme !== null || isPasswordSaving || isLoggingOut;
  const accountReady = !!principal && !!account && !loadError && !isLoading;

  const handleProfileSave = async (event: FormEvent) => {
    event.preventDefault();
    if (!principal || !accountReady || !profileDirty || profileError || isMutating) return;
    setIsProfileSaving(true);
    try {
      const wanted = { username: cleanUsername, full_name: cleanName, email: cleanEmail };
      const receipt = verifyAccount(await apiClient.put<unknown>("/api/auth/me", wanted), principal);
      if (
        receipt.username !== wanted.username ||
        receipt.full_name !== wanted.full_name ||
        receipt.email.toLowerCase() !== wanted.email
      ) throw new Error("Karen did not confirm the requested account changes.");

      // Verify read-after-write before showing a successful save.
      const verified = verifyAccount(await apiClient.get<unknown>("/api/auth/me"), principal);
      if (
        verified.username !== wanted.username ||
        verified.full_name !== wanted.full_name ||
        verified.email.toLowerCase() !== wanted.email
      ) throw new Error("The saved account details could not be verified. Refresh before retrying.");
      applyAccount(verified);
      toast({ title: "Profile saved", description: "Your updated account details were verified in Karen." });
    } catch (error) {
      toast({
        title: "Profile save not verified",
        description: errorMessage(error, "Refresh the profile before attempting another save."),
        variant: "destructive",
      });
    } finally {
      setIsProfileSaving(false);
    }
  };

  const handleThemeChange = async (nextTheme: Theme) => {
    if (!principal || !accountReady || isMutating || !isTheme(nextTheme) || theme === nextTheme) return;
    setPendingTheme(nextTheme);
    try {
      const receipt = verifyAccount(await apiClient.put<unknown>("/api/auth/me", {
        preferences: { theme: nextTheme },
      }), principal);
      if (receipt.preferences.theme !== nextTheme) {
        throw new Error("The selected theme was not confirmed by Karen.");
      }
      const verified = verifyAccount(await apiClient.get<unknown>("/api/auth/me"), principal);
      if (verified.preferences.theme !== nextTheme) {
        throw new Error("The saved display preference could not be verified.");
      }
      setAccount(verified);
      authService.updateCurrentUser({ preferences: verified.preferences });
      setTheme(nextTheme);
      toast({ title: "Display preference saved", description: "Your theme follows this account on your next sign-in." });
    } catch (error) {
      toast({
        title: "Theme change not verified",
        description: errorMessage(error, "Refresh your account before retrying."),
        variant: "destructive",
      });
    } finally {
      setPendingTheme(null);
    }
  };

  const handlePasswordChange = async (event: FormEvent) => {
    event.preventDefault();
    if (!accountReady || isMutating) return;
    if (!currentPassword || !newPassword || !confirmPassword) {
      toast({ title: "Password fields required", description: "Enter all three password fields.", variant: "destructive" });
      return;
    }
    if (newPassword === currentPassword) {
      toast({ title: "Choose a different password", description: "Your new password must differ from the current one.", variant: "destructive" });
      return;
    }
    if (newPassword !== confirmPassword) {
      toast({ title: "Passwords do not match", description: "Re-enter the new password confirmation.", variant: "destructive" });
      return;
    }

    setIsPasswordSaving(true);
    try {
      await apiClient.post("/api/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
    } catch (error) {
      toast({ title: "Password change failed", description: errorMessage(error, "Karen could not update your password."), variant: "destructive" });
      setIsPasswordSaving(false);
      return;
    }

    // The canonical password service revokes active sessions. Do not attempt
    // a second mutation on an ambiguous response or treat logout as a
    // prerequisite for recording the already-confirmed password change.
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    toast({ title: "Password changed", description: "Sign in again with your new password." });
    await logout();
    router.replace("/login?reason=password-changed");
  };

  const handleLogout = async () => {
    if (isMutating) return;
    setIsLoggingOut(true);
    try {
      await logout();
      router.replace("/login");
    } catch (error) {
      toast({ title: "Sign-out failed", description: errorMessage(error, "Unable to complete sign-out."), variant: "destructive" });
      setIsLoggingOut(false);
    }
  };

  if (authLoading || isLoading) {
    return (
      <section aria-label="My Account" className="space-y-6">
        <h2 className="karen-page-title">My Account</h2>
        <p role="status" className="text-sm text-muted-foreground">Loading your account securely...</p>
      </section>
    );
  }

  if (!accountReady || !account) {
    return (
      <section aria-label="My Account" className="space-y-5">
        <h2 className="karen-page-title">My Account</h2>
        <p className="text-sm text-muted-foreground">Manage your profile, display preferences, and security settings.</p>
        <Card>
          <CardHeader>
            <CardTitle>Account details unavailable</CardTitle>
            <CardDescription role="alert">{loadError || "Karen could not verify your active account."}</CardDescription>
          </CardHeader>
          <CardFooter>
            <Button variant="outline" onClick={() => void loadProfile()} disabled={!principal}>
              <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
              Retry account verification
            </Button>
          </CardFooter>
        </Card>
      </section>
    );
  }

  const chosenName = cleanName || cleanUsername || "Member";

  return (
    <section aria-label="My Account" className="space-y-6">
      <div className="space-y-1">
        <h2 className="karen-page-title">My Account</h2>
        <p className="text-sm text-muted-foreground">
          Manage your profile, display preferences, and security settings.
        </p>
      </div>
      <Separator />

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(260px,1fr)_minmax(0,2fr)]">
        <div className="min-w-0">
          <Card>
            <CardHeader className="items-center text-center">
              <Avatar className="mb-3 h-24 w-24">
                <AvatarImage src={account.avatarUrl || ""} alt={account.full_name || account.username} />
                <AvatarFallback className="text-2xl">{getInitials(account.full_name || account.username)}</AvatarFallback>
              </Avatar>
              <CardTitle className="break-words text-xl">{account.full_name || account.username || "Member"}</CardTitle>
              <CardDescription>{readableRoles(account.roles)}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center gap-2 text-muted-foreground">
                <UserRound className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="min-w-0 break-all">@{account.username}</span>
              </div>
              <div className="flex items-center gap-2 text-muted-foreground">
                <Mail className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="min-w-0 break-all">{account.email}</span>
              </div>
              <Separator />
              <p className="text-muted-foreground">Account created: {formatDate(account.created_at)}</p>
              <p className="text-muted-foreground">Last sign-in: {formatDate(account.last_login)}</p>
            </CardContent>
            <CardFooter>
              <Button variant="outline" className="w-full" onClick={() => void handleLogout()} disabled={isMutating}>
                <LogOut className="mr-2 h-4 w-4" aria-hidden="true" />
                {isLoggingOut ? "Signing out..." : "Sign out"}
              </Button>
            </CardFooter>
          </Card>
        </div>

        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Profile information</CardTitle>
              <CardDescription>Changes are applied to your own account, not the workspace or other members.</CardDescription>
            </CardHeader>
            <form onSubmit={(event) => void handleProfileSave(event)} noValidate>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="account-username">Username</Label>
                  <div className="relative">
                    <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                    <Input id="account-username" value={username} maxLength={64}
                      onChange={(event) => setUsername(event.target.value)}
                      className="pl-10" autoComplete="username" disabled={isMutating} />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="account-full-name">Display name</Label>
                  <Input id="account-full-name" value={fullName} maxLength={128}
                    onChange={(event) => setFullName(event.target.value)}
                    autoComplete="name" disabled={isMutating} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="account-email">Email address</Label>
                  <Input id="account-email" type="email" value={email} maxLength={254}
                    onChange={(event) => setEmail(event.target.value)}
                    autoComplete="email" disabled={isMutating} />
                </div>
                {profileDirty && (
                  <p role="status" className="text-xs text-muted-foreground">You have unsaved profile changes.</p>
                )}
                {profileDirty && profileError && (
                  <p role="alert" className="text-sm text-destructive">{profileError}</p>
                )}
              </CardContent>
              <CardFooter className="flex flex-wrap items-center justify-between gap-3 border-t pt-5">
                <Button type="button" variant="outline" onClick={() => void loadProfile(true)}
                  disabled={isMutating}>
                  <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
                  Refresh
                </Button>
                <Button type="submit" disabled={!profileDirty || !!profileError || isMutating}>
                  <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                  {isProfileSaving ? "Verifying save..." : "Save changes"}
                </Button>
              </CardFooter>
            </form>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Appearance</CardTitle>
              <CardDescription>Saved to this account and used when you sign in on another device.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <RadioGroup value={theme} onValueChange={(value) => {
                if (isTheme(value)) void handleThemeChange(value);
              }} disabled={isMutating} aria-label="Display theme"
                className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {([
                  { value: "light" as const, label: "Light", Icon: Sun },
                  { value: "dark" as const, label: "Dark", Icon: Moon },
                  { value: "system" as const, label: "System", Icon: Monitor },
                ]).map(({ value, label, Icon }) => (
                  <div key={value}>
                    <RadioGroupItem value={value} id={`account-theme-${value}`} className="peer sr-only" />
                    <Label htmlFor={`account-theme-${value}`}
                      className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-border/60 p-4 text-sm hover:bg-accent peer-data-[state=checked]:border-primary peer-data-[state=checked]:bg-primary/5 peer-focus-visible:ring-2 peer-focus-visible:ring-ring">
                      <Icon className="h-5 w-5" aria-hidden="true" />
                      {label}
                    </Label>
                  </div>
                ))}
              </RadioGroup>
              {pendingTheme && <p role="status" className="text-xs text-muted-foreground">Verifying display preference...</p>}
              <p className="text-xs text-muted-foreground">System follows your device appearance preference.</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="h-5 w-5" aria-hidden="true" />
                Account security
              </CardTitle>
              <CardDescription>
                Change your password. On success, Karen revokes existing sessions and requires a new sign-in.
              </CardDescription>
            </CardHeader>
            <form onSubmit={(event) => void handlePasswordChange(event)}>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="account-current-password">Current password</Label>
                  <Input id="account-current-password" type="password" autoComplete="current-password"
                    value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)}
                    disabled={isMutating} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="account-new-password">New password</Label>
                  <div className="relative">
                    <Input id="account-new-password" type={passwordVisible ? "text" : "password"}
                      autoComplete="new-password" className="pr-11"
                      value={newPassword} onChange={(event) => setNewPassword(event.target.value)}
                      disabled={isMutating} />
                    <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                      aria-label={passwordVisible ? "Hide new password" : "Show new password"}
                      aria-pressed={passwordVisible} onClick={() => setPasswordVisible((prev) => !prev)}
                      disabled={isMutating}>
                      {passwordVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="account-confirm-password">Confirm new password</Label>
                  <Input id="account-confirm-password" type={passwordVisible ? "text" : "password"}
                    autoComplete="new-password" value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    disabled={isMutating} />
                </div>
                <p className="text-xs text-muted-foreground">
                  Your new password must meet your account&apos;s security policy. Passwords are never displayed in your profile.
                </p>
              </CardContent>
              <CardFooter className="border-t pt-5">
                <Button type="submit" disabled={isMutating || !currentPassword || !newPassword || !confirmPassword}>
                  <Lock className="mr-2 h-4 w-4" aria-hidden="true" />
                  {isPasswordSaving ? "Updating password..." : "Update password"}
                </Button>
              </CardFooter>
            </form>
          </Card>

          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
            Account changes require your authenticated session and server verification.
          </p>
        </div>
      </div>
    </section>
  );
}
