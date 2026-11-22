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

interface PendingAuthorApproval {
  approval_id: string;
  status: string;
  intent: string;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA256 = /^[a-f0-9]{64}$/;

function isCandidate(value: OwnerArtifact): boolean {
  return (
    UUID.test(value.id) &&
    ['attachment', 'document'].includes(value.kind) &&
    value.mime_type === 'text/plain' &&
    Number.isInteger(value.size_bytes) &&
    value.size_bytes >= 1 &&
    value.size_bytes <= 65536 &&
    SHA256.test(value.sha256) &&
    value.deleted_at == null &&
    typeof value.filename === 'string' &&
    value.filename.length > 0
  );
}

/** Source picker only. The backend owns identity, policy, and approval scope. */
export function DocumentAuthorConsentInitiation() {
  const router = useRouter();
  const [documents, setDocuments] = useState<OwnerArtifact[]>([]);
  const [selectedDocument, setSelectedDocument] = useState('');
  const [profileId, setProfileId] = useState('');
  const [allowStyleUse, setAllowStyleUse] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void apiClient.get<OwnerArtifact[]>('/api/artifacts/').then((results) => {
      if (!active) return;
      if (!Array.isArray(results)) {
        setError('Document inventory is unavailable.');
        return;
      }
      setDocuments(results.filter(isCandidate));
    }).catch(() => {
      if (active) setError('Your documents could not be verified.');
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, []);

  const selected = documents.find((item) => item.id === selectedDocument);
  const canSubmit = Boolean(
    selected && UUID.test(profileId) && !loading && !submitting,
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
      {selected && (
        <dl className="space-y-2 break-all text-sm">
          <div><dt className="font-medium">Selected source ID</dt><dd>{selected.id}</dd></div>
          <div><dt className="font-medium">Current listed SHA-256</dt><dd>{selected.sha256}</dd></div>
          <div><dt className="font-medium">MIME type</dt><dd>{selected.mime_type}</dd></div>
        </dl>
      )}
      <label className="block space-y-2 text-sm">
        <span className="font-medium">Existing draft writing-style profile ID</span>
        <input
          aria-label="Existing draft writing-style profile ID"
          value={profileId}
          onChange={(event) => setProfileId(event.target.value.trim())}
          disabled={submitting}
          placeholder="Profile UUID"
          autoComplete="off"
          spellCheck={false}
          className="w-full rounded-md border border-border bg-background p-2"
        />
        <span className="block text-muted-foreground">
          The server verifies that this profile belongs to the authenticated author
          and is still an eligible draft. Entering an ID grants no access.
        </span>
      </label>
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
