"use client";

/**
 * Single browser-module authority for an in-flight credential rotation.
 *
 * The canonical AuthService and the ApiClient must never independently consume
 * the same single-use refresh credential in one browser JavaScript realm.
 * This coordinates network execution, not session ownership or authorization.
 *
 * Cross-tab isolation requires a separate, browser-level lock and a verified
 * credential-generation check; this module intentionally makes no such claim.
 */
let activeRefresh: Promise<string> | null = null;

export function runCoordinatedRefresh(
  rotate: () => Promise<string>,
): Promise<string> {
  if (activeRefresh) {
    return activeRefresh;
  }

  const pending = rotate();
  activeRefresh = pending;

  const release = (): void => {
    if (activeRefresh === pending) {
      activeRefresh = null;
    }
  };

  // Both handlers prevent an unhandled rejection from an ignored .finally().
  void pending.then(release, release);
  return pending;
}
