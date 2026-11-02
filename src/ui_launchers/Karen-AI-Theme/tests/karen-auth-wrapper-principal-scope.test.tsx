import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Principal = { user_id: string; tenant_id: string } | null;
const auth = vi.hoisted(() => ({
  current: {
    user: { user_id: "user-a", tenant_id: "tenant-one" } as Principal,
    isAuthenticated: true,
    isLoading: false,
  },
  redirect: vi.fn(),
}));

vi.mock("@/lib/useAuth", () => ({
  useAuth: () => auth.current,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ replace: auth.redirect }),
}));

import { AuthWrapper } from "@/components/AuthWrapper";

let nextMountId = 0;

function OwnedConversationState() {
  const [mountId] = React.useState(() => ++nextMountId);
  return <span data-testid="owned-conversation-state">instance-{mountId}</span>;
}

function renderScopedConversation() {
  return render(
    <AuthWrapper>
      <OwnedConversationState />
    </AuthWrapper>,
  );
}

beforeEach(() => {
  auth.current.user = { user_id: "user-a", tenant_id: "tenant-one" };
  auth.current.isAuthenticated = true;
  auth.current.isLoading = false;
  auth.redirect.mockReset();
  nextMountId = 0;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("authenticated dashboard principal isolation", () => {
  it("preserves mounted conversation state for an unchanged tenant and user", () => {
    const view = renderScopedConversation();
    expect(screen.getByTestId("owned-conversation-state").textContent).toBe("instance-1");
    auth.current.user = { user_id: "user-a", tenant_id: "tenant-one" };
    view.rerender(<AuthWrapper><OwnedConversationState /></AuthWrapper>);
    expect(screen.getByTestId("owned-conversation-state").textContent).toBe("instance-1");
  });

  it("unmounts the previous user's owned session even without an unauthenticated intermediate render", () => {
    const view = renderScopedConversation();
    expect(screen.getByTestId("owned-conversation-state").textContent).toBe("instance-1");
    auth.current.user = { user_id: "user-b", tenant_id: "tenant-one" };
    view.rerender(<AuthWrapper><OwnedConversationState /></AuthWrapper>);
    expect(screen.getByTestId("owned-conversation-state").textContent).toBe("instance-2");
  });

  it("unmounts the old tenant's conversation state for the same user ID", () => {
    const view = renderScopedConversation();
    auth.current.user = { user_id: "user-a", tenant_id: "tenant-two" };
    view.rerender(<AuthWrapper><OwnedConversationState /></AuthWrapper>);
    expect(screen.getByTestId("owned-conversation-state").textContent).toBe("instance-2");
  });

  it("uses collision-safe principal keys instead of ambiguous concatenation", () => {
    auth.current.user = { user_id: "b:c", tenant_id: "a" };
    const view = renderScopedConversation();
    auth.current.user = { user_id: "c", tenant_id: "a:b" };
    view.rerender(<AuthWrapper><OwnedConversationState /></AuthWrapper>);
    expect(screen.getByTestId("owned-conversation-state").textContent).toBe("instance-2");
  });

  it("fails closed if authentication is true but a canonical user or tenant is absent", () => {
    const view = renderScopedConversation();
    auth.current.user = null;
    view.rerender(<AuthWrapper><OwnedConversationState /></AuthWrapper>);
    expect(screen.queryByTestId("owned-conversation-state")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Verifying account identity");

    auth.current.user = { user_id: "user-a", tenant_id: "" };
    view.rerender(<AuthWrapper><OwnedConversationState /></AuthWrapper>);
    expect(screen.queryByTestId("owned-conversation-state")).toBeNull();
  });

  it("unmounts conversation state immediately on authentication invalidation", () => {
    const view = renderScopedConversation();
    auth.current.isAuthenticated = false;
    view.rerender(<AuthWrapper><OwnedConversationState /></AuthWrapper>);
    expect(screen.queryByTestId("owned-conversation-state")).toBeNull();
    expect(screen.getByText("Redirecting to login...")).not.toBeNull();
    expect(auth.redirect).toHaveBeenCalledWith("/login?next=%2Fdashboard");
  });
});
