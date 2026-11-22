'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { apiClient } from '@/lib/api';

interface OwnerArtifact {
  id: string;
  kind: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  deleted_at: string | null;
}

interface OwnerArtifactPage {
  items: OwnerArtifact[];
  has_more: boolean;
  next_cursor: string | null;
}

interface DraftProfile {
  profile_id: string;
  label: string;
  kind: string;
}

interface PendingAuthorApproval {
  approval_id: string;
  status: string;
  intent: string;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA256 = /^[a-f0-9]{64}$/;
// Mirrors the canonical bounded source reader's safe basename contract.
// Presentation filtering only: the backend still owns all authorization.
const SOURCE_FILENAME = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,159}$/;

function isCandidate(value: OwnerArtifact): boolean {
  return (
    value != null &&
    typeof value === 'object' &&
    UUID.test(value.id) &&
    ['attachment', 'document'].includes(value.kind) &&
    value.mime_type === 'text/plain' &&
    Number.isInteger(value.size_bytes) &&
    value.size_bytes >= 1 &&
    value.size_bytes <= 65536 &&
    SHA256.test(value.sha256) &&
    value.deleted_at == null &&
    typeof value.filename === 'string' &&
    SOURCE_FILENAME.test(value.filename) &&
    !['.', '..'].includes(value.filename) &&
    /\.(txt|md)$/i.test(value.filename)
  );
}

function isDraftProfile(value: unknown): value is DraftProfile {
  if (value == null || typeof value !== 'object') return false;
  const profile = value as Partial<DraftProfile>;
  return typeof profile.profile_id === 'string' && UUID.test(profile.profile_id) &&
    typeof profile.label === 'string' && profile.label.trim().length > 0 &&
    typeof profile.kind === 'string';
}

function isValidOwnerPage(page: OwnerArtifactPage | null | undefined, cursor: string | null): page is OwnerArtifactPage {
  if (!page || !Array.isArray(page.items) || page.items.length > 100 ||
      typeof page.has_more !== 'boolean') return false;
  if (page.has_more) {
    return page.items.length > 0 && typeof page.next_cursor === 'string' &&
      page.next_cursor.length >= 1 && page.next_cursor.length <= 768 &&
      page.next_cursor !== cursor;
  }
  return page.next_cursor === null;
}

/** Source picker only. The backend owns identity, policy, and approval scope. */
export function DocumentAuthorConsentInitiation() {
  const router = useRouter();
  const [documents, setDocuments] = useState<OwnerArtifact[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  // Counts completed, validated inventory pages, not requests in flight.
  const [loadedPages, setLoadedPages] = useState(0);
  const [profiles, setProfiles] = useState<DraftProfile[]>([]);
  const [selectedDocument, setSelectedDocument] = useState('');
  const [profileId, setProfileId] = useState('');
  const [allowStyleUse, setAllowStyleUse] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.all([
      apiClient.get<OwnerArtifactPage>('/api/artifacts/owner-page?limit=100'),
      apiClient.get<DraftProfile[]>('/api/approvals/document-consent/profiles'),
    ]).then(([page, drafts]) => {
      if (!active) return;
      if (!isValidOwnerPage(page, null) || !Array.isArray(drafts)) {
        setError('Document and draft-profile inventory is unavailable.');
        return;
      }
      setDocuments(page.items.filter(isCandidate));
      setLoadedPages(1);
      setNextCursor(page.has_more ? page.next_cursor : null);
      setProfiles(drafts.filter(isDraftProfile));
    }).catch(() => {
      if (active) setError('Your documents and draft profiles could not be verified.');
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, []);

  async function loadMoreDocuments() {
    if (!nextCursor || loading || loadingMore || submitting) return;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await apiClient.get<OwnerArtifactPage>(
        '/api/artifacts/owner-page?limit=100&cursor=' + encodeURIComponent(nextCursor),
      );
      if (!isValidOwnerPage(page, nextCursor)) {
        throw new Error('Invalid owner page');
      }
      setDocuments((previous) => {
        const seen = new Set(previous.map((item) => item.id));
        return [...previous, ...page.items.filter((item) => isCandidate(item) && !seen.has(item.id))];
      });
      setNextCursor(page.has_more ? page.next_cursor : null);
      setLoadedPages((count) => count + 1);
    } catch {
      setError('The next owned document page could not be verified. No new selection was authorized.');
    } finally {
      setLoadingMore(false);
    }
  }

  const selected = documents.find((item) => item.id === selectedDocument);
  const canSubmit = Boolean(
    selected && profiles.some((profile) => profile.profile_id === profileId) &&
    !loading && !loadingMore && !submitting && !error,
  );

  async function initiate() {
    if (!canSubmit || !selected) return;
    setSubmitting(true);
    setError(null);
    try {
      const approval = await apiClient.post<PendingAuthorApproval>(
        '/api/approvals/document-consent/initiate',
        {
          profile_id: profileId,
          artifact_id: selected.id,
          style_use_allowed: allowStyleUse,
        },
      );
      if (
        !UUID.test(approval.approval_id) ||
        approval.status !== 'pending' ||
        approval.intent !== 'writing_style.document_consent.issue'
      ) {
        throw new Error('No verified pending document approval.');
      }
      router.push(
        '/approvals/document-consent/' + encodeURIComponent(approval.approval_id),
      );
    } catch {
      setError(
        'Document review could not be initiated. No consent or ingestion has occurred.',
      );
      setSubmitting(false);
    }
  }

  return (
    <section
      aria-label="Initiate document author consent"
      data-owner-pages-loaded={loadedPages}
      className="mx-auto max-w-2xl space-y-5 rounded-lg border border-border p-6"
    >
      <h1 className="text-xl font-semibold">Review your document authorship</h1>
      <p className="text-sm text-muted-foreground">
        Select an existing document you authored. This requests a separate
        author review; it does not grant consent, analyze text, or ingest content.
      </p>
      {loading && <p role="status">Loading owned document metadata…</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {!loading && documents.length === 0 && (
        <p role="status">
          No eligible documents were returned by your document store.
          This screen cannot authorize an unlisted document.
        </p>
      )}
      {documents.length > 0 && (
        <label className="block space-y-2 text-sm">
          <span className="font-medium">Your document</span>
          <select
            aria-label="Your document"
            value={selectedDocument}
            onChange={(event) => setSelectedDocument(event.target.value)}
            disabled={submitting}
            className="w-full rounded-md border border-border bg-background p-2"
          >
            <option value="">Select an existing document</option>
            {documents.map((item) => (
              <option key={item.id} value={item.id}>
                {item.filename} ({item.size_bytes} bytes)
              </option>
            ))}
          </select>
        </label>
      )}
      {nextCursor && (
        <button
          type="button"
          onClick={() => { void loadMoreDocuments(); }}
          disabled={loading || loadingMore || submitting}
          className="rounded-md border border-border px-4 py-2 disabled:opacity-50"
        >
          {loadingMore ? 'Loading documents…' : 'Load more owned documents'}
        </button>
      )}
      {selected && (
        <dl className="space-y-2 break-all text-sm">
          <div><dt className="font-medium">Selected source ID</dt><dd>{selected.id}</dd></div>
          <div><dt className="font-medium">Current listed SHA-256</dt><dd>{selected.sha256}</dd></div>
          <div><dt className="font-medium">MIME type</dt><dd>{selected.mime_type}</dd></div>
        </dl>
      )}
      {!loading && profiles.length === 0 && (
        <p role="status">
          No eligible author-owned draft profiles were returned. This screen
          cannot authorize a missing or unpublished profile.
        </p>
      )}
      {profiles.length > 0 && (
        <label className="block space-y-2 text-sm">
          <span className="font-medium">Your draft writing-style profile</span>
          <select
            aria-label="Your draft writing-style profile"
            value={profileId}
            onChange={(event) => setProfileId(event.target.value)}
            disabled={submitting}
            className="w-full rounded-md border border-border bg-background p-2"
          >
            <option value="">Select an existing draft profile</option>
            {profiles.map((profile) => (
              <option key={profile.profile_id} value={profile.profile_id}>
                {profile.label} ({profile.kind})
              </option>
            ))}
          </select>
          <span className="block text-muted-foreground">
            The backend rechecks profile ownership and draft eligibility on submission.
            Selecting a profile is not author consent.
          </span>
        </label>
      )}
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={allowStyleUse}
          disabled={submitting}
          onChange={(event) => setAllowStyleUse(event.target.checked)}
        />
        <span>
          Request permission to apply my writing style to generated content.
          Leave unchecked to request analysis permission only.
          Neither choice is consent until the separate author confirmation.
        </span>
      </label>
      <button
        type="button"
        disabled={!canSubmit}
        onClick={() => { void initiate(); }}
        className="rounded-md border border-border px-4 py-2 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? 'Requesting review…' : 'Continue to author review'}
      </button>
      <p className="text-xs text-muted-foreground">
        Document ingestion remains disabled. The confirmation screen obtains
        its source identity and permissions from the backend, not this form.
      </p>
    </section>
  );
}
