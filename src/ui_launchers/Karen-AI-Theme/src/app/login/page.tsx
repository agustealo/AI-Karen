"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Brain, Loader2, LockKeyhole, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PublicWrapper } from "@/components/PublicWrapper";
import { useAuth } from "@/lib/useAuth";
import { setupService } from "@/lib/setup";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, isAuthenticated, isLoading, error } = useAuth();
  const [checkingSetup, setCheckingSetup] = useState(true);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [formData, setFormData] = useState({ email: "", username: "", password: "" });
  const [loginMode, setLoginMode] = useState<"email" | "username">("email");

  const nextPath = useMemo(() => {
    const candidate = searchParams.get("next");
    if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) {
      return "/dashboard";
    }
    return candidate;
  }, [searchParams]);

  useEffect(() => {
    let cancelled = false;

    const checkSetup = async () => {
      try {
        const status = await setupService.getFirstRunStatus();
        if (!cancelled && status.first_run_required) {
          router.replace("/setup");
          return;
        }
        if (!cancelled) {
          setSetupError(null);
          setCheckingSetup(false);
        }
      } catch {
        if (!cancelled) {
          setSetupError("Karen could not verify installation state. Check the backend and database before signing in.");
          setCheckingSetup(false);
        }
      }
    };

    void checkSetup();
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    if (!checkingSetup && !isLoading && isAuthenticated) {
      router.replace(nextPath);
    }
  }, [checkingSetup, isAuthenticated, isLoading, nextPath, router]);

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target;
    setFormData((previous) => ({ ...previous, [name]: value }));
  };

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const credentials = {
      ...(loginMode === "email" ? { email: formData.email } : { username: formData.username }),
      password: formData.password,
    };
    await login(credentials);
    router.replace(nextPath);
  };

  if (checkingSetup) {
    return (
      <PublicWrapper>
        <div className="flex min-h-screen items-center justify-center bg-background">
          <div className="flex flex-col items-center gap-3 text-sm text-muted-foreground">
            <Loader2 className="h-7 w-7 animate-spin" />
            <span>Checking Karen installation…</span>
          </div>
        </div>
      </PublicWrapper>
    );
  }

  return (
    <PublicWrapper>
      <main className="min-h-screen bg-background px-4 py-8 md:px-8 md:py-12">
        <div className="mx-auto grid min-h-[calc(100vh-6rem)] w-full max-w-5xl items-center gap-8 lg:grid-cols-[1fr_420px]">
          <section className="hidden rounded-3xl border bg-muted/30 p-10 lg:block">
            <div className="mb-12 flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl border bg-background shadow-sm">
                <Brain className="h-6 w-6 text-primary" />
              </div>
              <div>
                <p className="font-semibold">Karen AI</p>
                <p className="text-sm text-muted-foreground">Governed local-first intelligence</p>
              </div>
            </div>
            <h1 className="max-w-xl text-4xl font-semibold tracking-tight">
              Your runtime, memory, tools, and models stay behind one trusted identity boundary.
            </h1>
            <div className="mt-10 grid gap-4 text-sm text-muted-foreground">
              <div className="flex items-center gap-3">
                <ShieldCheck className="h-4 w-4 text-foreground" />
                Backend-enforced permissions and tenant scope
              </div>
              <div className="flex items-center gap-3">
                <LockKeyhole className="h-4 w-4 text-foreground" />
                Protected session with no default production credentials
              </div>
            </div>
          </section>

          <Card className="w-full border shadow-sm">
            <CardHeader className="space-y-2">
              <div className="mb-2 flex h-11 w-11 items-center justify-center rounded-2xl border bg-muted lg:hidden">
                <Brain className="h-6 w-6 text-primary" />
              </div>
              <CardTitle className="text-2xl">Welcome back</CardTitle>
              <CardDescription>Sign in to continue to Karen.</CardDescription>
            </CardHeader>
            <CardContent>
              {(error || setupError) && (
                <div className="mb-5 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
                  {error || setupError}
                </div>
              )}

              <div className="mb-5 grid grid-cols-2 rounded-xl border bg-muted/30 p-1">
                <button
                  type="button"
                  className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    loginMode === "email" ? "bg-background shadow-sm" : "text-muted-foreground"
                  }`}
                  onClick={() => setLoginMode("email")}
                >
                  Email
                </button>
                <button
                  type="button"
                  className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    loginMode === "username" ? "bg-background shadow-sm" : "text-muted-foreground"
                  }`}
                  onClick={() => setLoginMode("username")}
                >
                  Username
                </button>
              </div>

              <form onSubmit={handleLogin} className="space-y-4">
                <div className="grid gap-2">
                  <Label htmlFor={loginMode === "email" ? "email" : "username"}>
                    {loginMode === "email" ? "Email" : "Username"}
                  </Label>
                  <Input
                    id={loginMode === "email" ? "email" : "username"}
                    type={loginMode === "email" ? "email" : "text"}
                    name={loginMode === "email" ? "email" : "username"}
                    autoComplete={loginMode === "email" ? "email" : "username"}
                    value={loginMode === "email" ? formData.email : formData.username}
                    onChange={handleInputChange}
                    placeholder={loginMode === "email" ? "you@example.com" : "username"}
                    required
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    name="password"
                    autoComplete="current-password"
                    value={formData.password}
                    onChange={handleInputChange}
                    required
                  />
                </div>
                <Button type="submit" className="w-full" size="lg" disabled={isLoading || Boolean(setupError)}>
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Signing in…
                    </>
                  ) : (
                    "Sign in"
                  )}
                </Button>
              </form>

              <p className="mt-5 text-center text-xs leading-5 text-muted-foreground">
                New installation? Karen automatically opens secure first-run setup before this screen.
              </p>
            </CardContent>
          </Card>
        </div>
      </main>
    </PublicWrapper>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
