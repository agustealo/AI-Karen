"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Brain,
  Check,
  CheckCircle2,
  Database,
  Loader2,
  LockKeyhole,
  Server,
  ShieldCheck,
  Sparkles,
  UserRound,
  XCircle,
} from "lucide-react";
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
import { setupService, type SystemReadiness } from "@/lib/setup";

type Step = "readiness" | "account" | "complete";

const initialReadiness: SystemReadiness = {
  api: "error",
  auth: "error",
  database: "unknown",
};

export default function SetupPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("readiness");
  const [checking, setChecking] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<SystemReadiness>(initialReadiness);
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    confirm_password: "",
  });

  const passwordChecks = useMemo(
    () => ({
      length: form.password.length >= 12,
      upper: /[A-Z]/.test(form.password),
      lower: /[a-z]/.test(form.password),
      number: /\d/.test(form.password),
      symbol: /[^A-Za-z0-9]/.test(form.password),
      match: form.password.length > 0 && form.password === form.confirm_password,
    }),
    [form.password, form.confirm_password],
  );

  const passwordReady = Object.values(passwordChecks).every(Boolean);
  const servicesReady =
    readiness.api === "ready" &&
    readiness.auth === "ready" &&
    readiness.database !== "unknown";

  const runPreflight = async () => {
    setChecking(true);
    setError(null);

    try {
      const status = await setupService.getFirstRunStatus();
      if (!status.first_run_required) {
        router.replace("/login");
        return;
      }

      const nextReadiness = await setupService.getSystemReadiness();
      setReadiness(nextReadiness);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to verify setup state.");
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    void runPreflight();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const createOwner = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!passwordReady) {
      setError("Complete the password requirements before continuing.");
      return;
    }

    setSubmitting(true);
    try {
      await setupService.createFirstAdmin(form);
      setStep("complete");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Setup failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <PublicWrapper>
      <main className="min-h-screen bg-background px-4 py-8 md:px-8 md:py-12">
        <div className="mx-auto grid w-full max-w-6xl gap-8 lg:grid-cols-[0.9fr_1.1fr]">
          <section className="flex flex-col justify-between rounded-3xl border bg-muted/30 p-7 md:p-10">
            <div>
              <div className="mb-8 flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl border bg-background shadow-sm">
                  <Brain className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <p className="font-semibold">Karen AI</p>
                  <p className="text-sm text-muted-foreground">Private-first runtime setup</p>
                </div>
              </div>

              <div className="space-y-4">
                <div className="inline-flex items-center gap-2 rounded-full border bg-background px-3 py-1 text-xs font-medium">
                  <Sparkles className="h-3.5 w-3.5" />
                  First-run experience
                </div>
                <h1 className="max-w-xl text-3xl font-semibold tracking-tight md:text-5xl">
                  Build your Karen around you, not around a config file.
                </h1>
                <p className="max-w-lg text-base leading-7 text-muted-foreground">
                  Verify the local system, create the installation owner, and enter Karen already authenticated. No demo credentials. No curl ceremony.
                </p>
              </div>
            </div>

            <div className="mt-10 grid gap-3 text-sm text-muted-foreground">
              <SetupPrinciple icon={ShieldCheck} text="Backend-owned installation truth" />
              <SetupPrinciple icon={LockKeyhole} text="Secure first administrator bootstrap" />
              <SetupPrinciple icon={Database} text="Local service readiness before account creation" />
            </div>
          </section>

          <section className="flex items-center">
            <Card className="w-full border shadow-sm">
              <CardHeader className="space-y-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <CardTitle className="text-2xl">
                      {step === "readiness" && "System check"}
                      {step === "account" && "Create the installation owner"}
                      {step === "complete" && "Karen is ready"}
                    </CardTitle>
                    <CardDescription className="mt-1">
                      {step === "readiness" && "Karen is verifying the services required to finish setup."}
                      {step === "account" && "This is the first trusted administrator for this installation."}
                      {step === "complete" && "Your owner account is active and the authenticated session is ready."}
                    </CardDescription>
                  </div>
                  <div className="rounded-full border px-3 py-1 text-xs font-medium text-muted-foreground">
                    {step === "readiness" ? "1 / 3" : step === "account" ? "2 / 3" : "3 / 3"}
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <StepBar active={true} complete={step !== "readiness"} />
                  <StepBar active={step !== "readiness"} complete={step === "complete"} />
                  <StepBar active={step === "complete"} complete={step === "complete"} />
                </div>
              </CardHeader>

              <CardContent>
                {error && (
                  <div className="mb-5 flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
                    <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}

                {step === "readiness" && (
                  <div className="space-y-6">
                    <div className="grid gap-3">
                      <ReadinessRow
                        icon={Server}
                        label="Karen API"
                        description="Core application runtime"
                        status={checking ? "checking" : readiness.api}
                      />
                      <ReadinessRow
                        icon={ShieldCheck}
                        label="Authentication"
                        description="Identity and session authority"
                        status={checking ? "checking" : readiness.auth}
                      />
                      <ReadinessRow
                        icon={Database}
                        label="Database"
                        description="Durable account and session storage"
                        status={checking ? "checking" : readiness.database}
                      />
                    </div>

                    <div className="rounded-xl border bg-muted/30 p-4 text-sm text-muted-foreground">
                      Provider, model, memory, and extension choices stay in their canonical runtime settings. This first-run flow only establishes trusted ownership and proves the installation is healthy enough to proceed.
                    </div>

                    <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
                      {!checking && !servicesReady && (
                        <Button variant="outline" onClick={() => void runPreflight()}>
                          Check again
                        </Button>
                      )}
                      <Button
                        onClick={() => setStep("account")}
                        disabled={checking || !servicesReady}
                      >
                        Continue
                        <ArrowRight className="ml-2 h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                )}

                {step === "account" && (
                  <form className="space-y-5" onSubmit={createOwner}>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div className="grid gap-2 sm:col-span-2">
                        <Label htmlFor="full_name">Full name</Label>
                        <Input
                          id="full_name"
                          autoComplete="name"
                          value={form.full_name}
                          onChange={(event) => setForm({ ...form, full_name: event.target.value })}
                          placeholder="Your name"
                          required
                        />
                      </div>
                      <div className="grid gap-2 sm:col-span-2">
                        <Label htmlFor="email">Email</Label>
                        <Input
                          id="email"
                          type="email"
                          autoComplete="email"
                          value={form.email}
                          onChange={(event) => setForm({ ...form, email: event.target.value })}
                          placeholder="you@example.com"
                          required
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor="password">Password</Label>
                        <Input
                          id="password"
                          type="password"
                          autoComplete="new-password"
                          value={form.password}
                          onChange={(event) => setForm({ ...form, password: event.target.value })}
                          required
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor="confirm_password">Confirm password</Label>
                        <Input
                          id="confirm_password"
                          type="password"
                          autoComplete="new-password"
                          value={form.confirm_password}
                          onChange={(event) =>
                            setForm({ ...form, confirm_password: event.target.value })
                          }
                          required
                        />
                      </div>
                    </div>

                    <div className="grid gap-2 rounded-xl border bg-muted/20 p-4 sm:grid-cols-2">
                      <PasswordCheck ok={passwordChecks.length} label="12+ characters" />
                      <PasswordCheck ok={passwordChecks.upper} label="Uppercase letter" />
                      <PasswordCheck ok={passwordChecks.lower} label="Lowercase letter" />
                      <PasswordCheck ok={passwordChecks.number} label="Number" />
                      <PasswordCheck ok={passwordChecks.symbol} label="Symbol" />
                      <PasswordCheck ok={passwordChecks.match} label="Passwords match" />
                    </div>

                    <div className="rounded-xl border bg-muted/30 p-4 text-sm text-muted-foreground">
                      <div className="flex gap-3">
                        <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0" />
                        <p>
                          This account receives the installation&apos;s initial admin role. Karen will keep authorization on the backend and use a protected browser session after setup.
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
                      <Button type="button" variant="outline" onClick={() => setStep("readiness")}>
                        Back
                      </Button>
                      <Button type="submit" disabled={submitting || !passwordReady}>
                        {submitting ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Creating owner…
                          </>
                        ) : (
                          <>
                            Create owner
                            <ArrowRight className="ml-2 h-4 w-4" />
                          </>
                        )}
                      </Button>
                    </div>
                  </form>
                )}

                {step === "complete" && (
                  <div className="space-y-6">
                    <div className="flex flex-col items-center rounded-2xl border bg-muted/20 px-6 py-10 text-center">
                      <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-primary">
                        <CheckCircle2 className="h-8 w-8" />
                      </div>
                      <h2 className="text-xl font-semibold">Installation owner created</h2>
                      <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                        Karen has established the first trusted user and authenticated this browser. Runtime configuration stays governed by the backend and can be completed from the application.
                      </p>
                    </div>

                    <Button className="w-full" size="lg" onClick={() => router.replace("/dashboard")}>
                      Open Karen
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          </section>
        </div>
      </main>
    </PublicWrapper>
  );
}

function StepBar({ active, complete }: { active: boolean; complete: boolean }) {
  return (
    <div
      className={`h-1.5 rounded-full transition-colors ${
        complete || active ? "bg-primary" : "bg-muted"
      }`}
    />
  );
}

function SetupPrinciple({
  icon: Icon,
  text,
}: {
  icon: React.ComponentType<{ className?: string }>;
  text: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <Icon className="h-4 w-4 text-foreground" />
      <span>{text}</span>
    </div>
  );
}

function ReadinessRow({
  icon: Icon,
  label,
  description,
  status,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  description: string;
  status: "ready" | "error" | "degraded" | "unknown" | "checking";
}) {
  const ready = status === "ready";
  const checking = status === "checking";
  const detail =
    status === "ready"
      ? "Ready"
      : status === "degraded"
        ? "Degraded"
        : status === "unknown"
          ? "Unavailable"
          : status === "checking"
            ? "Checking"
            : "Error";

  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted">
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-sm font-medium">{label}</p>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </div>
      <div className="flex items-center gap-2 text-sm">
        {checking ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : ready ? (
          <CheckCircle2 className="h-4 w-4 text-primary" />
        ) : (
          <XCircle className="h-4 w-4 text-destructive" />
        )}
        <span className={ready ? "text-foreground" : "text-muted-foreground"}>{detail}</span>
      </div>
    </div>
  );
}

function PasswordCheck({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className={`flex items-center gap-2 text-xs ${ok ? "text-foreground" : "text-muted-foreground"}`}>
      <span
        className={`flex h-4 w-4 items-center justify-center rounded-full border ${
          ok ? "border-primary bg-primary text-primary-foreground" : "border-muted-foreground/30"
        }`}
      >
        {ok && <Check className="h-2.5 w-2.5" />}
      </span>
      {label}
    </div>
  );
}
