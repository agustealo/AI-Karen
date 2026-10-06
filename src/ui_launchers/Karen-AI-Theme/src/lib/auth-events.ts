export const AUTH_INVALIDATED_EVENT = 'karen:auth-invalidated';

export interface AuthInvalidatedDetail {
  reason: 'terminal_401' | 'refresh_failed' | 'session_invalid';
}

export const dispatchAuthInvalidated = (
  reason: AuthInvalidatedDetail['reason'],
): void => {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(
    new CustomEvent<AuthInvalidatedDetail>(AUTH_INVALIDATED_EVENT, {
      detail: { reason },
    }),
  );
};
