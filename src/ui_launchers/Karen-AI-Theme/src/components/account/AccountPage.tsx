"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Lock, LogOut, Mail, Moon, RefreshCw, Save, Shield, Sun, User } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";
import { useTheme } from "@/providers/theme-provider";

interface UserPreferences {
  theme?: string;
  [key: string]: unknown;
}

interface AccountUser {
  user_id: string;
  email: string;
  full_name: string;
  username: string;
  roles: string[];
  is_active: boolean;
  created_at: string;
  last_login?: string | null;
  tenant_id: string;
  preferences: UserPreferences;
  avatarUrl?: string;
}

const EMPTY_ACCOUNT: AccountUser = {
  user_id: "",
  email: "",
  full_name: "",
  username: "",
  roles: [],
  is_active: true,
  created_at: "",
  last_login: null,
  tenant_id: "",
  preferences: {},
  avatarUrl: "",
};

function getInitials(name: string): string {
  const normalized = name.trim();
  if (!normalized) {
    return "KA";
  }

  const names = normalized.split(/\s+/);
  if (names.length === 1) {
    return names[0].charAt(0).toUpperCase();
  }

  return `${names[0].charAt(0)}${names[names.length - 1].charAt(0)}`.toUpperCase();
}

function formatDisplayDate(value?: string | null): string {
  if (!value) {
    return "Never";
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

function formatRoleLabel(roles: string[]): string {
  if (!roles.length) {
    return "User";
  }

  return roles
    .map((role) => role.replace(/_/g, " "))
    .map((role) => role.charAt(0).toUpperCase() + role.slice(1))
    .join(", ");
}

export default function AccountPage() {
  const router = useRouter();
  const { toast } = useToast();
  const { logout, refreshSession } = useAuth();
  const { theme, setTheme } = useTheme();

  const [account, setAccount] = useState<AccountUser>(EMPTY_ACCOUNT);
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isProfileSaving, setIsProfileSaving] = useState(false);
  const [isPasswordSaving, setIsPasswordSaving] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  const applyAccount = useCallback((user: AccountUser) => {
    setAccount(user);
    setUsername(user.username || "");
    setFullName(user.full_name || "");
    setEmail(user.email || "");
  }, []);

  const loadProfile = useCallback(async (showSuccessToast = false) => {
    try {
      setIsLoading(true);
      const user = await apiClient.get<AccountUser>("/api/auth/me");
      applyAccount(user);

      if (!user.username && user.email) {
        setUsername(user.email.split("@")[0]);
      }

      const preferredTheme = user.preferences?.theme;
      if ((preferredTheme === "light" || preferredTheme === "dark") && preferredTheme !== theme) {
        setTheme(preferredTheme);
      }

      if (showSuccessToast) {
        toast({
          title: "Profile Refreshed",
          description: "Your profile data has been refreshed from Karen.",
        });
      }
    } catch (error) {
      toast({
        title: "Profile unavailable",
        description: error instanceof Error ? error.message : "Unable to load your account profile.",
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
    }
  }, [applyAccount, setTheme, theme, toast]);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  const profileIncomplete = !username.trim() || !fullName.trim();

  const handleProfileSave = async (event: React.FormEvent) => {
    event.preventDefault();

    if (profileIncomplete) {
      toast({
        title: "Profile incomplete",
        description: "Username and full name are required.",
        variant: "destructive",
      });
      return;
    }

    try {
      setIsProfileSaving(true);
      const updated = await apiClient.put<AccountUser>("/api/auth/me", {
        username: username.trim(),
        full_name: fullName.trim(),
        email: email.trim(),
      });
      applyAccount(updated);

      if (refreshSession) {
        await refreshSession();
      }

      toast({
        title: "Profile Updated",
        description: "Your account information has been saved.",
      });
    } catch (error) {
      toast({
        title: "Save Failed",
        description: error instanceof Error ? error.message : "Unable to save your account profile.",
        variant: "destructive",
      });
    } finally {
      setIsProfileSaving(false);
    }
  };

  const handleThemeChange = async (value: "light" | "dark") => {
    const previousTheme = theme;
    setTheme(value);

    try {
      const updated = await apiClient.put<AccountUser>("/api/auth/me", {
        preferences: { theme: value },
      });
      setAccount(updated);
    } catch (error) {
      setTheme(previousTheme);
      toast({
        title: "Theme update failed",
        description: error instanceof Error ? error.message : "Unable to save theme preference.",
        variant: "destructive",
      });
    }
  };

  const handlePasswordChange = async (event: React.FormEvent) => {
    event.preventDefault();

    if (!currentPassword || !newPassword || !confirmPassword) {
      toast({
        title: "Password fields required",
        description: "Enter your current password and confirm the new password.",
        variant: "destructive",
      });
      return;
    }

    if (newPassword !== confirmPassword) {
      toast({
        title: "Passwords do not match",
        description: "The new password and confirmation must match.",
        variant: "destructive",
      });
      return;
    }

    try {
      setIsPasswordSaving(true);
      await apiClient.post("/api/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });

      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");

      toast({
        title: "Password Changed",
        description: "For security, Karen signed out this session. Sign in again with your new password.",
      });

      await logout();
      router.replace("/login?reason=password-changed");
    } catch (error) {
      toast({
        title: "Update Failed",
        description: error instanceof Error ? error.message : "Unable to change your password.",
        variant: "destructive",
      });
    } finally {
      setIsPasswordSaving(false);
    }
  };

  const handleLogout = async () => {
    try {
      setIsLoggingOut(true);
      await logout();
      router.replace("/login");
    } catch (error) {
      toast({
        title: "Logout failed",
        description: error instanceof Error ? error.message : "Unable to log out.",
        variant: "destructive",
      });
    } finally {
      setIsLoggingOut(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">My Account</h2>
        <p className="text-sm text-muted-foreground">
          Manage your profile, display preferences, and security settings.
        </p>
      </div>
      <Separator />

      <div className="grid gap-8 md:grid-cols-3">
        <div className="md:col-span-1">
          <Card>
            <CardHeader className="items-center text-center">
              <Avatar className="mb-2 h-24 w-24">
                <AvatarImage src={account.avatarUrl || ""} alt={fullName || username} />
                <AvatarFallback className="text-3xl">{getInitials(fullName || username)}</AvatarFallback>
              </Avatar>
              <CardTitle className="text-xl">{fullName || username || "Karen User"}</CardTitle>
              <CardDescription>{formatRoleLabel(account.roles)}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-center text-sm text-muted-foreground">
              <p>@{username || "unconfigured"}</p>
              <p>Account created: {formatDisplayDate(account.created_at)}</p>
              <p>Last login: {formatDisplayDate(account.last_login)}</p>
            </CardContent>
            <CardFooter>
              <Button variant="outline" className="w-full" onClick={handleLogout} disabled={isLoggingOut}>
                <LogOut className="mr-2 h-4 w-4" />
                {isLoggingOut ? "Logging out..." : "Logout"}
              </Button>
            </CardFooter>
          </Card>
        </div>

        <div className="space-y-8 md:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Profile Information</CardTitle>
              <CardDescription>These values are saved to your canonical account record.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="username" className={profileIncomplete && !username.trim() ? "text-orange-600" : ""}>
                  Username (Handle)
                </Label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="username"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    className="pl-10"
                    disabled={isLoading || isProfileSaving}
                    placeholder="admin"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="full-name" className={profileIncomplete && !fullName.trim() ? "text-orange-600" : ""}>
                  Full Name (Display)
                </Label>
                <div className="relative">
                  <Shield className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="full-name"
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                    className="pl-10"
                    disabled={isLoading || isProfileSaving}
                    placeholder="System Administrator"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="email">Email Address</Label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    className="pl-10"
                    disabled={isLoading || isProfileSaving}
                  />
                </div>
              </div>
            </CardContent>
            <CardFooter className="flex justify-between border-t pt-6">
              <Button variant="outline" onClick={() => void loadProfile(true)} disabled={isLoading || isProfileSaving}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Refresh Profile
              </Button>
              <Button onClick={handleProfileSave} disabled={isLoading || isProfileSaving || profileIncomplete}>
                <Save className="mr-2 h-4 w-4" />
                {isProfileSaving ? "Saving..." : "Save Changes"}
              </Button>
            </CardFooter>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Display Settings</CardTitle>
              <CardDescription>Choose your preferred theme.</CardDescription>
            </CardHeader>
            <CardContent>
              <RadioGroup
                value={theme}
                onValueChange={(value: "light" | "dark") => void handleThemeChange(value)}
                className="grid grid-cols-2 gap-4"
              >
                <div>
                  <RadioGroupItem value="light" id="light" className="peer sr-only" />
                  <Label htmlFor="light" className="flex flex-col items-center justify-between rounded-md border-2 border-muted bg-popover p-4 hover:bg-accent peer-data-[state=checked]:border-primary">
                    <Sun className="mb-3 h-6 w-6" />
                    Light
                  </Label>
                </div>
                <div>
                  <RadioGroupItem value="dark" id="dark" className="peer sr-only" />
                  <Label htmlFor="dark" className="flex flex-col items-center justify-between rounded-md border-2 border-muted bg-popover p-4 hover:bg-accent peer-data-[state=checked]:border-primary">
                    <Moon className="mb-3 h-6 w-6" />
                    Dark
                  </Label>
                </div>
              </RadioGroup>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Security Settings</CardTitle>
              <CardDescription>Changing your password revokes the current session and requires a fresh sign-in.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="current-password">Current Password</Label>
                <Input id="current-password" type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} disabled={isPasswordSaving} autoComplete="current-password" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="new-password">New Password</Label>
                <Input id="new-password" type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} disabled={isPasswordSaving} autoComplete="new-password" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm-password">Confirm New Password</Label>
                <Input id="confirm-password" type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} disabled={isPasswordSaving} autoComplete="new-password" />
              </div>
            </CardContent>
            <CardFooter className="border-t pt-6">
              <Button onClick={handlePasswordChange} disabled={isPasswordSaving}>
                <Lock className="mr-2 h-4 w-4" />
                {isPasswordSaving ? "Updating..." : "Update Password"}
              </Button>
            </CardFooter>
          </Card>
        </div>
      </div>
    </div>
  );
}
