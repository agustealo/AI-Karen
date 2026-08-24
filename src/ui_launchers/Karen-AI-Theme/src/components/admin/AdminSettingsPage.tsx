"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  BarChart,
  Ban,
  Bell,
  Bot,
  BrainCircuit,
  Database,
  Eye,
  EyeOff,
  FileText,
  GraduationCap,
  MoreHorizontal,
  PenSquare,
  PlusCircle,
  Search,
  Shield,
  Trash2,
  UserCog,
  UserPlus,
  Users,
  X,
  Wrench,
} from "lucide-react";

import { apiClient, ApiError } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import AdminAnalyticsPanel from "./AdminAnalyticsPanel";
import AdminDatabasePanel from "./AdminDatabasePanel";
import AuditLogPanel from "./AuditLogPanel";
import FallbackModelSettings from "./FallbackModelSettings";
import MaintenancePanel from "./MaintenancePanel";
import SystemConfigPanel from "./SystemConfigPanel";
import TrainingSettingsPanel from "./TrainingSettingsPanel";
import CommsCenterPage from "@/components/comms/CommsCenterPage";

type UserRole = "Admin" | "User" | "Editor";
type BackendRole = "admin" | "user" | "editor";
type UserStatus = "Active" | "Suspended" | "Pending";
type DialogMode = "view" | "edit";

type User = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  status: UserStatus;
  createdAt: string;
  createdAtRaw: string;
  lastLogin: string | null;
  timeSpent: string | null;
  tokenUsage: number | null;
};

type BackendUserResponse = {
  user_id: string;
  email: string;
  full_name?: string | null;
  tenant_id: string;
  roles: string[];
  preferences: Record<string, unknown>;
  is_active: boolean;
  is_verified: boolean;
  last_login?: string | null;
  created_at: string;
  updated_at: string;
};

type UserMetricsResponse = {
  user_id: string;
  hours: number;
  event_count: number;
  session_count: number;
  total_session_minutes: number;
  average_session_minutes: number;
  last_seen?: string | null;
  token_usage?: number | null;
  token_usage_supported: boolean;
};

type AuthStatsResponse = {
  status?: string;
  service?: string;
  timestamp?: string;
  stats?: {
    total_users?: number;
    active_users?: number;
    total_sessions?: number;
    active_sessions?: number;
    service_status?: string;
    error?: string;
  };
};

type CreateUserForm = {
  name: string;
  email: string;
  password: string;
  role: BackendRole;
};

type EditUserForm = {
  name: string;
  email: string;
  role: UserRole;
  status: UserStatus;
};

const ROLE_OPTIONS: Array<{ label: UserRole; value: BackendRole }> = [
  { label: "User", value: "user" },
  { label: "Editor", value: "editor" },
  { label: "Admin", value: "admin" },
];

const STATUS_OPTIONS: UserStatus[] = ["Active", "Pending", "Suspended"];

const DEFAULT_CREATE_FORM: CreateUserForm = {
  name: "",
  email: "",
  password: "",
  role: "user",
};

const DEFAULT_EDIT_FORM: EditUserForm = {
  name: "",
  email: "",
  role: "User",
  status: "Active",
};

const normalizeBackendRole = (roles: string[]): UserRole => {
  const normalizedRoles = roles.map((role) => role.toLowerCase());

  if (normalizedRoles.includes("admin")) {
    return "Admin";
  }

  if (normalizedRoles.includes("editor")) {
    return "Editor";
  }

  return "User";
};

const toBackendRole = (role: UserRole): BackendRole => {
  switch (role) {
    case "Admin":
      return "admin";
    case "Editor":
      return "editor";
    case "User":
    default:
      return "user";
  }
};

const getUserStatus = (user: BackendUserResponse): UserStatus => {
  if (!user.is_verified) {
    return "Pending";
  }

  return user.is_active ? "Active" : "Suspended";
};

const getStatusUpdatePayload = (status: UserStatus) => {
  if (status === "Pending") {
    return { is_active: true, is_verified: false };
  }

  if (status === "Suspended") {
    return { is_active: false, is_verified: true };
  }

  return { is_active: true, is_verified: true };
};

const getInitials = (name: string) => {
  const cleaned = name.trim();

  if (!cleaned) {
    return "U";
  }

  const names = cleaned.split(/\s+/);

  if (names.length === 1) {
    return names[0].charAt(0).toUpperCase();
  }

  return `${names[0].charAt(0)}${names[names.length - 1].charAt(0)}`.toUpperCase();
};

const getStatusBadgeVariant = (status: UserStatus) => {
  switch (status) {
    case "Active":
      return "secondary" as const;
    case "Suspended":
      return "destructive" as const;
    case "Pending":
      return "outline" as const;
    default:
      return "secondary" as const;
  }
};

const getRoleBadgeVariant = (role: UserRole) => {
  switch (role) {
    case "Admin":
      return "default" as const;
    case "Editor":
      return "secondary" as const;
    case "User":
    default:
      return "outline" as const;
  }
};

const formatNumber = (num: number) => {
  if (num >= 1_000_000) {
    return `${(num / 1_000_000).toFixed(1)}M`;
  }

  if (num >= 1_000) {
    return `${(num / 1_000).toFixed(1)}K`;
  }

  return num.toString();
};

const formatDateTime = (value: string | null | undefined) => {
  if (!value) {
    return "Not recorded";
  }

  const parsed = new Date(value);

  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString();
};

const formatDate = (value: string | null | undefined) => {
  if (!value) {
    return "Not recorded";
  }

  const parsed = new Date(value);

  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleDateString();
};

const getErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof ApiError) {
    return error.message || fallback;
  }

  if (error instanceof Error) {
    return error.message || fallback;
  }

  return fallback;
};

const isValidEmail = (value: string) => {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
};

const isStrongPassword = (value: string) => {
  const password = value.trim();

  if (password.length < 8) {
    return false;
  }

  return (
    /[A-Z]/.test(password) &&
    /[a-z]/.test(password) &&
    /\d/.test(password) &&
    /[!@#$%^&*()_+\-=[\]{}|;:,.<>?]/.test(password)
  );
};

const mapBackendUser = (user: BackendUserResponse): User => ({
  id: user.user_id,
  name: user.full_name?.trim() || user.email || user.user_id,
  email: user.email,
  role: normalizeBackendRole(user.roles),
  status: getUserStatus(user),
  createdAt: formatDate(user.created_at),
  createdAtRaw: user.created_at,
  lastLogin: user.last_login || null,
  timeSpent: null,
  tokenUsage: null,
});

export default function AdminSettingsPage() {
  const { toast } = useToast();

  const [users, setUsers] = useState<User[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  const [usersAuthRequired, setUsersAuthRequired] = useState(false);
  const [usersAccessDenied, setUsersAccessDenied] = useState(false);
  const [usersLoadError, setUsersLoadError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");

  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editDialogMode, setEditDialogMode] = useState<DialogMode>("edit");

  const [userMetrics, setUserMetrics] = useState<UserMetricsResponse | null>(null);
  const [userMetricsLoading, setUserMetricsLoading] = useState(false);
  const [userMetricsError, setUserMetricsError] = useState<string | null>(null);
  const [authStats, setAuthStats] = useState<AuthStatsResponse["stats"] | null>(null);
  const [authStatsError, setAuthStatsError] = useState<string | null>(null);

  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [isCreatingUser, setIsCreatingUser] = useState(false);
  const [isUpdatingUser, setIsUpdatingUser] = useState(false);
  const [showCreatePassword, setShowCreatePassword] = useState(false);

  const [createForm, setCreateForm] = useState<CreateUserForm>(DEFAULT_CREATE_FORM);
  const [editForm, setEditForm] = useState<EditUserForm>(DEFAULT_EDIT_FORM);

  const canManageUsers = !usersLoading && !usersAuthRequired && !usersAccessDenied;
  const canCreateUser =
    canManageUsers &&
    !isCreatingUser &&
    createForm.email.trim().length > 0 &&
    isValidEmail(createForm.email) &&
    isStrongPassword(createForm.password);

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    setUsersAuthRequired(false);
    setUsersAccessDenied(false);
    setUsersLoadError(null);

    try {
      const response = await apiClient.get<BackendUserResponse[]>("/api/admin/users");

      if (!Array.isArray(response)) {
        setUsersAuthRequired(true);
        setUsers([]);
        return;
      }

      setUsers(response.map(mapBackendUser));
    } catch (error) {
      setUsers([]);

      if (error instanceof ApiError && error.status === 401) {
        setUsersAuthRequired(true);
        return;
      }

      if (error instanceof ApiError && error.status === 403) {
        setUsersAccessDenied(true);
        return;
      }

      setUsersLoadError(getErrorMessage(error, "Karen could not load backend users."));
    } finally {
      setUsersLoading(false);
    }
  }, []);

  const loadAuthStats = useCallback(async () => {
    setAuthStatsError(null);

    try {
      const response = await apiClient.get<AuthStatsResponse>("/api/auth/status");
      setAuthStats(response.stats || null);
    } catch (error) {
      setAuthStats(null);
      setAuthStatsError(
        getErrorMessage(error, "Karen could not load auth service statistics."),
      );
    }
  }, []);

  useEffect(() => {
    let mounted = true;

    const run = async () => {
      if (!mounted) {
        return;
      }

      await loadUsers();
    };

    void run();

    return () => {
      mounted = false;
    };
  }, [loadUsers]);

  useEffect(() => {
    void loadAuthStats();
  }, [loadAuthStats]);

  useEffect(() => {
    if (!editingUser) {
      setEditForm(DEFAULT_EDIT_FORM);
      return;
    }

    setEditForm({
      name: editingUser.name,
      email: editingUser.email,
      role: editingUser.role,
      status: editingUser.status,
    });
  }, [editingUser]);

  useEffect(() => {
    if (!editingUser) {
      setUserMetrics(null);
      setUserMetricsError(null);
      setUserMetricsLoading(false);
      return;
    }

    let mounted = true;

    const loadUserMetrics = async () => {
      setUserMetricsLoading(true);
      setUserMetricsError(null);

      try {
        const response = await apiClient.get<UserMetricsResponse>(
          `/api/admin/users/${encodeURIComponent(editingUser.id)}/metrics?hours=168`,
        );

        if (!mounted) {
          return;
        }

        setUserMetrics(response);
      } catch (error) {
        if (!mounted) {
          return;
        }

        setUserMetrics(null);
        setUserMetricsError(
          getErrorMessage(error, "Karen could not load backend user metrics."),
        );
      } finally {
        if (mounted) {
          setUserMetricsLoading(false);
        }
      }
    };

    void loadUserMetrics();

    return () => {
      mounted = false;
    };
  }, [editingUser]);

  const filteredUsers = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();

    if (!query) {
      return users;
    }

    return users.filter((user) => {
      return (
        user.name.toLowerCase().includes(query) ||
        user.email.toLowerCase().includes(query) ||
        user.role.toLowerCase().includes(query) ||
        user.status.toLowerCase().includes(query)
      );
    });
  }, [searchQuery, users]);

  const userCounts = useMemo(() => {
    const activeUsers = users.filter((user) => user.status === "Active").length;

    return {
      total: users.length || authStats?.total_users || 0,
      active: activeUsers || authStats?.active_users || 0,
      pending: users.filter((user) => user.status === "Pending").length,
      suspended: users.filter((user) => user.status === "Suspended").length,
    };
  }, [authStats?.active_users, authStats?.total_users, users]);

  const openUserDialog = (user: User, mode: DialogMode) => {
    setEditDialogMode(mode);
    setEditingUser(user);
  };

  const closeUserDialog = () => {
    if (isUpdatingUser) {
      return;
    }

    setEditingUser(null);
  };

  const resetCreateDialog = () => {
    if (isCreatingUser) {
      return;
    }

    setIsCreateDialogOpen(false);
    setCreateForm(DEFAULT_CREATE_FORM);
    setShowCreatePassword(false);
  };

  const validateCreateForm = () => {
    const email = createForm.email.trim();

    if (!email || !isValidEmail(email)) {
      return "Enter a valid email address.";
    }

    if (!createForm.password.trim()) {
      return "Enter a temporary password.";
    }

    if (!isStrongPassword(createForm.password)) {
      return "Temporary password must be 8+ characters and include uppercase, lowercase, a digit, and a special character.";
    }

    return null;
  };

  const validateEditForm = () => {
    if (!editForm.name.trim()) {
      return "Name cannot be empty.";
    }

    return null;
  };

  const handleCreateUser = async () => {
    const validationError = validateCreateForm();

    if (validationError) {
      toast({
        title: "Check user details",
        description: validationError,
        variant: "destructive",
      });
      return;
    }

    setIsCreatingUser(true);

    try {
      const trimmedEmail = createForm.email.trim();
      const fallbackName = trimmedEmail.split("@")[0] || trimmedEmail;
      const response = await apiClient.post<BackendUserResponse>("/api/admin/users", {
        email: trimmedEmail,
        password: createForm.password.trim(),
        full_name: createForm.name.trim() || fallbackName,
        roles: [createForm.role],
      });

      setIsCreateDialogOpen(false);
      setShowCreatePassword(false);
      setCreateForm(DEFAULT_CREATE_FORM);

      await loadUsers();

      toast({
        title: "User created",
        description: `${response.email} was added through Karen's backend user service.`,
      });
    } catch (error) {
      toast({
        title: "User creation failed",
        description: getErrorMessage(error, "Karen could not create the user."),
        variant: "destructive",
      });
    } finally {
      setIsCreatingUser(false);
    }
  };

  const handleSaveUser = async () => {
    if (!editingUser) {
      return;
    }

    const validationError = validateEditForm();

    if (validationError) {
      toast({
        title: "Check user details",
        description: validationError,
        variant: "destructive",
      });
      return;
    }

    setIsUpdatingUser(true);

    try {
      const response = await apiClient.put<BackendUserResponse>(
        `/api/admin/users/${encodeURIComponent(editingUser.id)}`,
        {
          full_name: editForm.name.trim(),
          roles: [toBackendRole(editForm.role)],
          ...getStatusUpdatePayload(editForm.status),
        },
      );

      await loadUsers();

      setEditingUser(null);

      toast({
        title: "User updated",
        description: `${response.email} was updated through Karen's backend user service.`,
      });
    } catch (error) {
      toast({
        title: "User update failed",
        description: getErrorMessage(error, "Karen could not update the user."),
        variant: "destructive",
      });
    } finally {
      setIsUpdatingUser(false);
    }
  };

  const handleToggleSuspend = async (userId: string) => {
    const targetUser = users.find((user) => user.id === userId);

    if (!targetUser) {
      return;
    }

    if (targetUser.status === "Pending") {
      toast({
        title: "Pending user",
        description:
          "This user is not verified yet. Verify or activate the account through the backend-approved flow before suspension changes.",
        variant: "destructive",
      });
      return;
    }

    const nextActiveState = targetUser.status !== "Active";

    try {
      const response = await apiClient.put<BackendUserResponse>(
        `/api/admin/users/${encodeURIComponent(userId)}`,
        {
          is_active: nextActiveState,
        },
      );

      await loadUsers();

      toast({
        title: nextActiveState ? "User unsuspended" : "User suspended",
        description: `${response.email} is now ${nextActiveState ? "active" : "suspended"}.`,
      });
    } catch (error) {
      toast({
        title: "User update failed",
        description: getErrorMessage(error, "Karen could not update the user status."),
        variant: "destructive",
      });
    }
  };

  const handleDeleteUser = async (userId: string) => {
    const targetUser = users.find((user) => user.id === userId);

    try {
      await apiClient.delete(`/api/admin/users/${encodeURIComponent(userId)}`);
      await loadUsers();

      if (editingUser?.id === userId) {
        setEditingUser(null);
      }

      toast({
        title: "User deleted",
        description: targetUser
          ? `${targetUser.email} was deleted through Karen's backend user service.`
          : "The selected user was deleted through Karen's backend user service.",
      });
    } catch (error) {
      toast({
        title: "User deletion failed",
        description: getErrorMessage(error, "Karen could not delete the user."),
        variant: "destructive",
      });
    }
  };

  return (
    <>
      <div className="space-y-6">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Shield className="h-6 w-6 text-primary" />
            Admin Settings
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage users, configure fallback models, monitor system health, and review audit logs.
          </p>
        </div>

        <Separator />

        <Tabs defaultValue="users" className="w-full">
          <TabsList className="flex h-auto w-full shrink-0 flex-wrap justify-start">
            <TabsTrigger value="users">
              <Users className="mr-1.5 h-4 w-4" />
              Users
            </TabsTrigger>
            <TabsTrigger value="models">
              <Bot className="mr-1.5 h-4 w-4" />
              Fallback Models
            </TabsTrigger>
            <TabsTrigger value="training">
              <GraduationCap className="mr-1.5 h-4 w-4" />
              Training
            </TabsTrigger>
            <TabsTrigger value="communications">
              <Bell className="mr-1.5 h-4 w-4" />
              Communications
            </TabsTrigger>
            <TabsTrigger value="system">
              <Activity className="mr-1.5 h-4 w-4" />
              System
            </TabsTrigger>
            <TabsTrigger value="database">
              <Database className="mr-1.5 h-4 w-4" />
              Database
            </TabsTrigger>
            <TabsTrigger value="analytics">
              <BarChart className="mr-1.5 h-4 w-4" />
              Analytics
            </TabsTrigger>
            <TabsTrigger value="audit">
              <FileText className="mr-1.5 h-4 w-4" />
              Audit Log
            </TabsTrigger>
            <TabsTrigger value="maintenance">
              <Wrench className="mr-1.5 h-4 w-4" />
              Maintenance
            </TabsTrigger>
          </TabsList>

          <TabsContent value="users" className="mt-6">
            <div className="mb-6 grid gap-4 md:grid-cols-2 lg:grid-cols-5">
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Total Users</CardTitle>
                  <Users className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{userCounts.total}</div>
                  <p className="text-xs text-muted-foreground">All registered users</p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Active Users</CardTitle>
                  <Users className="h-4 w-4 text-green-500" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{userCounts.active}</div>
                  <p className="text-xs text-muted-foreground">Users currently active</p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">User Metrics</CardTitle>
                  <BrainCircuit className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">Live</div>
                  <p className="text-xs text-muted-foreground">
                    Per-user metrics load from the backend details endpoint.
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Pending</CardTitle>
                  <UserPlus className="h-4 w-4 text-yellow-500" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{userCounts.pending}</div>
                  <p className="text-xs text-muted-foreground">Awaiting activation</p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Suspended</CardTitle>
                  <Users className="h-4 w-4 text-destructive" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{userCounts.suspended}</div>
                  <p className="text-xs text-muted-foreground">Suspended access</p>
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>User Management</CardTitle>
                <CardDescription>
                  View, manage, and control user accounts and roles through Karen&apos;s backend user
                  service.
                </CardDescription>
              </CardHeader>

              <CardContent>
                {authStatsError && (
                  <Alert className="mb-6 border-yellow-500/30 bg-yellow-500/5">
                    <AlertCircle className="h-4 w-4 !text-yellow-600" />
                    <AlertTitle>Auth Statistics Unavailable</AlertTitle>
                    <AlertDescription>{authStatsError}</AlertDescription>
                  </Alert>
                )}

                {usersAccessDenied && (
                  <Alert className="mb-6 border-primary/20 bg-primary/5">
                    <Shield className="h-4 w-4 !text-primary" />
                    <AlertTitle>User Access Restricted</AlertTitle>
                    <AlertDescription>
                      The users route is live, but this session is not authorized to list or manage
                      backend user records.
                    </AlertDescription>
                  </Alert>
                )}

                {usersAuthRequired && (
                  <Alert className="mb-6 border-primary/20 bg-primary/5">
                    <Shield className="h-4 w-4 !text-primary" />
                    <AlertTitle>Sign In Required</AlertTitle>
                    <AlertDescription>
                      The users route is live, but this session is not authenticated. Sign in before
                      listing or managing backend user records.
                    </AlertDescription>
                  </Alert>
                )}

                {usersLoadError && (
                  <Alert className="mb-6 border-yellow-500/30 bg-yellow-500/5">
                    <Activity className="h-4 w-4 !text-yellow-600" />
                    <AlertTitle>User Inventory Unavailable</AlertTitle>
                    <AlertDescription>{usersLoadError}</AlertDescription>
                  </Alert>
                )}

                <div className="mb-6 flex items-center justify-between gap-4">
                  <div className="flex flex-1 items-center gap-2">
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        placeholder="Search users by name, email, role, or status..."
                        className="max-w-md pl-10 pr-10"
                        value={searchQuery}
                        onChange={(event) => setSearchQuery(event.target.value)}
                      />
                      {searchQuery.trim() && (
                        <button
                          type="button"
                          onClick={() => setSearchQuery("")}
                          className="absolute inset-y-0 right-0 flex items-center justify-center px-3 text-muted-foreground transition-colors hover:text-foreground"
                          aria-label="Clear search"
                          title="Clear search"
                        >
                          <X className="h-4 w-4" aria-hidden="true" />
                        </button>
                      )}
                    </div>
                  </div>

                  <Dialog
                    open={isCreateDialogOpen}
                    onOpenChange={(open) => {
                      if (open) {
                        setIsCreateDialogOpen(true);
                      } else {
                        resetCreateDialog();
                      }
                    }}
                  >
                    <DialogTrigger asChild>
                      <Button disabled={!canManageUsers}>
                        <PlusCircle className="mr-2 h-4 w-4" />
                        Add User
                      </Button>
                    </DialogTrigger>

                    <DialogContent className="sm:max-w-[640px] lg:max-w-[720px] max-h-[85vh] overflow-y-auto">
                      <DialogHeader>
                        <DialogTitle>Add New User</DialogTitle>
                        <DialogDescription>
                          Create a new user account and assign them a role.
                        </DialogDescription>
                      </DialogHeader>

                      <div className="space-y-5 py-4">
                        <div className="grid gap-4 md:grid-cols-2">
                          <div className="space-y-2">
                            <Label htmlFor="create-name">Name</Label>
                            <Input
                              id="create-name"
                              placeholder="John Doe"
                              value={createForm.name}
                              onChange={(event) =>
                                setCreateForm((current) => ({
                                  ...current,
                                  name: event.target.value,
                                }))
                              }
                              disabled={isCreatingUser}
                            />
                          </div>

                          <div className="space-y-2">
                            <Label htmlFor="create-email">Email</Label>
                            <Input
                              id="create-email"
                              type="email"
                              placeholder="john@example.com"
                              className="bg-background text-foreground"
                              value={createForm.email}
                              onChange={(event) =>
                                setCreateForm((current) => ({
                                  ...current,
                                  email: event.target.value,
                                }))
                              }
                              disabled={isCreatingUser}
                            />
                          </div>
                        </div>

                        <div className="grid gap-4 md:grid-cols-[3fr_1fr]">
                          <div className="space-y-2">
                            <Label htmlFor="create-password">Password</Label>
                            <div className="relative">
                              <Input
                                id="create-password"
                                type={showCreatePassword ? "text" : "password"}
                                placeholder="Temporary password"
                                className="bg-background text-foreground pr-10"
                                value={createForm.password}
                                onChange={(event) =>
                                  setCreateForm((current) => ({
                                    ...current,
                                    password: event.target.value,
                                  }))
                                }
                                disabled={isCreatingUser}
                              />
                              <button
                                type="button"
                                onClick={() =>
                                  setShowCreatePassword((current) => !current)
                                }
                                className="absolute inset-y-0 right-0 flex items-center justify-center px-3 text-muted-foreground transition-colors hover:text-foreground"
                                aria-label={
                                  showCreatePassword
                                    ? "Hide password"
                                    : "Show password"
                                }
                                title={
                                  showCreatePassword
                                    ? "Hide password"
                                    : "Show password"
                                }
                                disabled={isCreatingUser}
                              >
                                {showCreatePassword ? (
                                  <EyeOff className="h-4 w-4" aria-hidden="true" />
                                ) : (
                                  <Eye className="h-4 w-4" aria-hidden="true" />
                                )}
                              </button>
                            </div>
                            <p className="text-xs text-muted-foreground">
                              Password must be 8+ characters and include uppercase, lowercase, a digit, and a special character.
                            </p>
                          </div>

                          <div className="space-y-2">
                            <Label htmlFor="create-role">Role</Label>
                            <Select
                              value={createForm.role}
                              onValueChange={(value) =>
                                setCreateForm((current) => ({
                                  ...current,
                                  role: value as BackendRole,
                                }))
                              }
                              disabled={isCreatingUser}
                            >
                              <SelectTrigger id="create-role" className="bg-background text-foreground">
                                <SelectValue placeholder="Select a role" />
                              </SelectTrigger>
                              <SelectContent>
                                {ROLE_OPTIONS.map((role) => (
                                  <SelectItem key={role.value} value={role.value}>
                                    {role.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                      </div>

                      <DialogFooter>
                        <DialogClose asChild>
                          <Button variant="outline" disabled={isCreatingUser}>
                            Cancel
                          </Button>
                        </DialogClose>
                        <Button
                          type="button"
                          onClick={() => void handleCreateUser()}
                          disabled={!canCreateUser}
                        >
                          {isCreatingUser ? "Creating..." : "Create User"}
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                </div>

                {usersLoading ? (
                  <div className="flex items-center gap-2 rounded-xl border border-border/70 p-4 text-sm text-muted-foreground">
                    <Activity className="h-4 w-4 animate-pulse" />
                    Loading backend user inventory.
                  </div>
                ) : filteredUsers.length === 0 ? (
                  <div className="rounded-xl border border-border/70 p-6 text-sm text-muted-foreground">
                    {searchQuery.trim()
                      ? `No users match "${searchQuery.trim()}". Clear search to show all backend users.`
                      : "No backend users were returned for this tenant or session."}
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[40px]">
                          <Checkbox disabled />
                        </TableHead>
                        <TableHead>User</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Role</TableHead>
                        <TableHead>Last Login</TableHead>
                        <TableHead>Time Spent</TableHead>
                        <TableHead className="text-right">Token Usage</TableHead>
                        <TableHead>Date Added</TableHead>
                        <TableHead className="text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>

                    <TableBody>
                      {filteredUsers.map((user) => (
                        <TableRow key={user.id}>
                          <TableCell>
                            <Checkbox disabled />
                          </TableCell>

                          <TableCell>
                            <div className="flex items-center gap-3">
                              <Avatar>
                                <AvatarFallback>{getInitials(user.name)}</AvatarFallback>
                              </Avatar>
                              <div>
                                <div className="font-medium">{user.name}</div>
                                <div className="text-sm text-muted-foreground">{user.email}</div>
                              </div>
                            </div>
                          </TableCell>

                          <TableCell>
                            <Badge variant={getStatusBadgeVariant(user.status)}>{user.status}</Badge>
                          </TableCell>

                          <TableCell>
                            <Badge variant={getRoleBadgeVariant(user.role)}>{user.role}</Badge>
                          </TableCell>

                          <TableCell>{formatDateTime(user.lastLogin)}</TableCell>

                          <TableCell>{user.timeSpent || "Not instrumented"}</TableCell>

                          <TableCell className="text-right">
                            {user.tokenUsage == null ? "Not instrumented" : formatNumber(user.tokenUsage)}
                          </TableCell>

                          <TableCell title={formatDateTime(user.createdAtRaw)}>{user.createdAt}</TableCell>

                          <TableCell className="text-right">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="icon">
                                  <MoreHorizontal className="h-4 w-4" />
                                </Button>
                              </DropdownMenuTrigger>

                              <DropdownMenuContent align="end">
                                <DropdownMenuLabel>Actions</DropdownMenuLabel>

                                <DropdownMenuItem onClick={() => openUserDialog(user, "view")}>
                                  <Eye className="mr-2 h-4 w-4" />
                                  View Details
                                </DropdownMenuItem>

                                <DropdownMenuItem onClick={() => openUserDialog(user, "edit")}>
                                  <PenSquare className="mr-2 h-4 w-4" />
                                  Edit User
                                </DropdownMenuItem>

                                <DropdownMenuItem onClick={() => openUserDialog(user, "edit")}>
                                  <UserCog className="mr-2 h-4 w-4" />
                                  Change Role
                                </DropdownMenuItem>

                                <DropdownMenuSeparator />

                                <DropdownMenuItem
                                  onClick={() => void handleToggleSuspend(user.id)}
                                  disabled={user.status === "Pending"}
                                >
                                  <Ban className="mr-2 h-4 w-4" />
                                  {user.status === "Active" ? "Suspend" : "Unsuspend"}
                                </DropdownMenuItem>

                                <AlertDialog>
                                  <AlertDialogTrigger asChild>
                                    <DropdownMenuItem
                                      className="text-destructive"
                                      onSelect={(event) => event.preventDefault()}
                                    >
                                      <Trash2 className="mr-2 h-4 w-4" />
                                      Delete User
                                    </DropdownMenuItem>
                                  </AlertDialogTrigger>

                                  <AlertDialogContent>
                                    <AlertDialogHeader>
                                      <AlertDialogTitle>Delete this user?</AlertDialogTitle>
                                      <AlertDialogDescription>
                                        This will delete the account for{" "}
                                        <span className="font-semibold">{user.name}</span>. This action
                                        should only succeed if the backend authorizes it and records the audit
                                        event.
                                      </AlertDialogDescription>
                                    </AlertDialogHeader>

                                    <AlertDialogFooter>
                                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                                      <AlertDialogAction
                                        className="bg-destructive hover:bg-destructive/90"
                                        onClick={() => void handleDeleteUser(user.id)}
                                      >
                                        Delete
                                      </AlertDialogAction>
                                    </AlertDialogFooter>
                                  </AlertDialogContent>
                                </AlertDialog>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="models" className="mt-6">
            <FallbackModelSettings />
          </TabsContent>

          <TabsContent value="training" className="mt-6">
            <TrainingSettingsPanel />
          </TabsContent>

          <TabsContent value="communications" className="mt-6">
            <CommsCenterPage />
          </TabsContent>

          <TabsContent value="system" className="mt-6">
            <SystemConfigPanel />
          </TabsContent>

          <TabsContent value="database" className="mt-6 space-y-6">
            <AdminDatabasePanel />
          </TabsContent>

          <TabsContent value="analytics" className="mt-6">
            <AdminAnalyticsPanel />
          </TabsContent>

          <TabsContent value="audit" className="mt-6">
            <AuditLogPanel />
          </TabsContent>

          <TabsContent value="maintenance" className="mt-6">
            <MaintenancePanel />
          </TabsContent>
        </Tabs>
      </div>

      <Dialog
        open={!!editingUser}
        onOpenChange={(open) => {
          if (!open) {
            closeUserDialog();
          }
        }}
      >
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>
              {editDialogMode === "view" ? "User Details" : "Edit User"}
              {editingUser ? `: ${editingUser.name}` : ""}
            </DialogTitle>
            <DialogDescription>
              {editDialogMode === "view"
                ? "Review backend-derived account details for this user."
                : "Modify account details through Karen's backend user service."}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-name" className="text-right">
                Name
              </Label>
              <Input
                id="edit-name"
                value={editForm.name}
                onChange={(event) =>
                  setEditForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                className="col-span-3"
                disabled={editDialogMode === "view" || isUpdatingUser}
              />
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-email" className="text-right">
                Email
              </Label>
              <Input id="edit-email" type="email" value={editForm.email} className="col-span-3" disabled />
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-role" className="text-right">
                Role
              </Label>
              <Select
                value={editForm.role}
                onValueChange={(value) =>
                  setEditForm((current) => ({
                    ...current,
                    role: value as UserRole,
                  }))
                }
                disabled={editDialogMode === "view" || isUpdatingUser}
              >
                <SelectTrigger id="edit-role" className="col-span-3">
                  <SelectValue placeholder="Select a role" />
                </SelectTrigger>
                <SelectContent>
                  {ROLE_OPTIONS.map((role) => (
                    <SelectItem key={role.label} value={role.label}>
                      {role.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-status" className="text-right">
                Status
              </Label>
              <Select
                value={editForm.status}
                onValueChange={(value) =>
                  setEditForm((current) => ({
                    ...current,
                    status: value as UserStatus,
                  }))
                }
                disabled={editDialogMode === "view" || isUpdatingUser}
              >
                <SelectTrigger id="edit-status" className="col-span-3">
                  <SelectValue placeholder="Select a status" />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((status) => (
                    <SelectItem key={status} value={status}>
                      {status}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-created-at" className="text-right">
                Created
              </Label>
              <Input
                id="edit-created-at"
                value={formatDateTime(editingUser?.createdAtRaw)}
                className="col-span-3"
                disabled
              />
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-last-login" className="text-right">
                Last Login
              </Label>
              <Input
                id="edit-last-login"
                value={formatDateTime(editingUser?.lastLogin)}
                className="col-span-3"
                disabled
              />
            </div>

            {userMetricsError && (
              <Alert className="border-yellow-500/30 bg-yellow-500/5">
                <Activity className="h-4 w-4 !text-yellow-600" />
                <AlertTitle>User Metrics Unavailable</AlertTitle>
                <AlertDescription>{userMetricsError}</AlertDescription>
              </Alert>
            )}

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-user-events" className="text-right">
                Events
              </Label>
              <Input
                id="edit-user-events"
                value={
                  userMetricsLoading
                    ? "Loading..."
                    : userMetrics
                      ? String(userMetrics.event_count)
                      : userMetricsError
                        ? "Unavailable"
                        : "Not recorded"
                }
                className="col-span-3"
                disabled
              />
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-user-sessions" className="text-right">
                Sessions
              </Label>
              <Input
                id="edit-user-sessions"
                value={
                  userMetricsLoading
                    ? "Loading..."
                    : userMetrics
                      ? String(userMetrics.session_count)
                      : userMetricsError
                        ? "Unavailable"
                        : "Not recorded"
                }
                className="col-span-3"
                disabled
              />
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-user-session-minutes" className="text-right">
                Session Minutes
              </Label>
              <Input
                id="edit-user-session-minutes"
                value={
                  userMetricsLoading
                    ? "Loading..."
                    : userMetrics
                      ? `${userMetrics.total_session_minutes.toFixed(
                          1,
                        )} total / ${userMetrics.average_session_minutes.toFixed(1)} avg`
                      : userMetricsError
                        ? "Unavailable"
                        : "Not recorded"
                }
                className="col-span-3"
                disabled
              />
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-user-last-seen" className="text-right">
                Last Seen
              </Label>
              <Input
                id="edit-user-last-seen"
                value={
                  userMetricsLoading
                    ? "Loading..."
                    : userMetrics?.last_seen
                      ? formatDateTime(userMetrics.last_seen)
                      : userMetricsError
                        ? "Unavailable"
                        : "Not recorded"
                }
                className="col-span-3"
                disabled
              />
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="edit-user-token-usage" className="text-right">
                Token Usage
              </Label>
              <Input
                id="edit-user-token-usage"
                value={
                  userMetricsLoading
                    ? "Loading..."
                    : userMetrics?.token_usage_supported
                      ? formatNumber(userMetrics.token_usage ?? 0)
                      : "Not instrumented"
                }
                className="col-span-3"
                disabled
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeUserDialog} disabled={isUpdatingUser}>
              {editDialogMode === "view" ? "Close" : "Cancel"}
            </Button>

            {editDialogMode === "edit" && (
              <Button
                type="button"
                onClick={() => void handleSaveUser()}
                disabled={isUpdatingUser || !editForm.name.trim()}
              >
                {isUpdatingUser ? "Saving..." : "Save Changes"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
