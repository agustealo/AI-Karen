/**
 * Topic registry for frontend.
 * Centralizes topic names with deterministic formatting.
 * Prevents arbitrary browser-supplied prefixes.
 */



const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function validateUuid(value: string, name: string): string {
  if (typeof value !== "string" || value.length !== 36 || !UUID_RE.test(value)) {
    throw new Error(`${name} must be a valid UUID`);
  }
  return value.toLowerCase();
}

export function userTopic(tenantId: string, userId: string): string {
  return `tenant:${validateUuid(tenantId, "tenantId")}:user:${validateUuid(userId, "userId")}`;
}

export function conversationTopic(tenantId: string, conversationId: string): string {
  return `tenant:${validateUuid(tenantId, "tenantId")}:conversation:${validateUuid(conversationId, "conversationId")}`;
}

export function executionTopic(tenantId: string, executionId: string): string {
  return `tenant:${validateUuid(tenantId, "tenantId")}:execution:${validateUuid(executionId, "executionId")}`;
}

export function tenantNotificationsTopic(tenantId: string): string {
  return `tenant:${validateUuid(tenantId, "tenantId")}:notifications`;
}

export function adminTopic(tenantId: string): string {
  return `tenant:${validateUuid(tenantId, "tenantId")}:admin`;
}

export function resolveTopic(topic: string): string | null {
  if (typeof topic !== "string") return null;
  const parts = topic.split(":");
  if ((parts.length !== 3 && parts.length !== 4) || parts[0] !== "tenant") return null;
  if (parts[1].length !== 36 || !UUID_RE.test(parts[1])) return null;
  const tenant = parts[1].toLowerCase();
  const kind = parts[2];
  if (kind === "user" || kind === "conversation" || kind === "execution") {
    if (parts.length !== 4 || parts[3].length !== 36 || !UUID_RE.test(parts[3])) return null;
    return `tenant:${tenant}:${kind}:${parts[3].toLowerCase()}`;
  }
  if ((kind === "notifications" || kind === "admin") && parts.length === 3) {
    return `tenant:${tenant}:${kind}`;
  }
  return null;
}

export class TopicRegistry {
  constructor(private tenantId: string) {}

  resolve(topic: string): string | null {
    const resolved = resolveTopic(topic);
    if (!resolved || typeof this.tenantId !== "string" ||
        this.tenantId.length !== 36 || !UUID_RE.test(this.tenantId)) return null;
    return resolved.split(":")[1] === this.tenantId.toLowerCase() ? resolved : null;
  }

  user(userId: string) {
    return userTopic(this.tenantId, userId);
  }
  conversation(conversationId: string) {
    return conversationTopic(this.tenantId, conversationId);
  }
  execution(executionId: string) {
    return executionTopic(this.tenantId, executionId);
  }
  notifications() {
    return tenantNotificationsTopic(this.tenantId);
  }
  admin() {
    return adminTopic(this.tenantId);
  }
}
