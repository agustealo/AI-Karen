/**
 * The canonical browser-to-Karen API cookie boundary.
 *
 * Vercel ingress/deployment cookies authorize only the frontend host.
 * Neither the generic proxy nor CopilotKit agent may forward these to
 * Karen's authenticated backend. Preserve all ordinary app cookies.
 */
export function sanitizeBackendCookies(rawCookies: string): string {
  // Keep Karen's app session while stripping Vercel's *frontend ingress*
  // authorization. A backend API never needs a deployment-bypass credential.
  return rawCookies.split(';').map(cookie => cookie.trim()).filter(cookie => {
    const eq = cookie.indexOf('=');
    if (eq <= 0) return false;
    const name = cookie.slice(0, eq).trim().toLowerCase();
    return name !== '_vercel_jwt' &&
      name !== '__vercel_protection_bypass';
  }).join('; ');
}

