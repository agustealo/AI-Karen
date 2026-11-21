'use client';

import { useEffect, useState } from 'react';

import { apiClient } from '@/lib/api';

interface ConsentPreview {
  approval_id: string;
  status: 'pending' | 'approved';
  profile_id: string;
  artifact_id: string;
  source_sha256: string;
  analysis_allowed: boolean;
  style_use_allowed: boolean;
  expires_at: string;
  approval_expires_at: string;
}

interface ApprovalDecision {
  approval_id: string;
  status: string;
}

const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const DIGEST = /^[a-f0-9]{64}$/;

export function DocumentAuthorConsentConfirmation({
  approvalId,
}: {
  approvalId: string;
}) {
  const [preview, setPreview] = useState<ConsentPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<ApprovalDecision | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setPreview(null);
    setConfirmed(false);
    setDecision(null);
    setError(null);
    if (!ID.test(approvalId)) {
      setError('Invalid approval reference.');
      setLoading(false);
      return;
    }
    void apiClient.get<ConsentPreview>(
      '/api/approvals/document-consent/' + approvalId,
    ).then((record) => {
      if (!active) return;
      if (
        record.approval_id !== approvalId ||
        (record.status !== 'pending' && record.status !== 'approved') ||
        !ID.test(record.profile_id) ||
        !ID.test(record.artifact_id) ||
        !DIGEST.test(record.source_sha256) ||
        record.analysis_allowed !== true ||
        typeof record.style_use_allowed !== 'boolean' ||
        !Number.isFinite(Date.parse(record.expires_at)) ||
        !Number.isFinite(Date.parse(record.approval_expires_at))
      ) {
        setError('Document authorization metadata could not be verified.');
      } else {
        setPreview(record);
      }
    }).catch(() => {
      if (active) setError('Document approval could not be verified. No consent was granted.');
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [approvalId]);

  const expires = preview
    ? Math.min(Date.parse(preview.expires_at), Date.parse(preview.approval_expires_at))
    : 0;
  const canConfirm =
    !!preview &&
    preview.status === 'pending' &&
    !loading &&
    !submitting &&
    !decision &&
    confirmed &&
    expires > Date.now();

  async function handleConfirm() {
    if (!canConfirm || !preview) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await apiClient.post<ApprovalDecision>(
        '/api/approvals/document-consent/' + preview.approval_id + '/confirm',
        { confirmed: true },
      );
      if (result.approval_id !== preview.approval_id || result.status !== 'approved') {
        throw new Error('Unexpected approval state.');
      }
      setDecision(result);
      setConfirmed(false);
    } catch {
      setError('Confirmation was not verified. No consent receipt is claimed.');
      setConfirmed(false);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section
      aria-label="Document author consent"
      className="mx-auto max-w-2xl space-y-5 rounded-lg border border-border p-6"
    >
      <h1 className="text-xl font-semibold">Document author confirmation</h1>
      <p className="text-sm text-muted-foreground">
        This decision is separate from chat approval. Confirm only if you authored
        this exact document and wish to authorize the uses shown below.
      </p>
      {loading && <p role="status">Verifying your current session and document approval…</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {preview && !decision && (
        <>
          <dl className="space-y-3 break-all text-sm">
            <div><dt className="font-medium">Document ID</dt><dd>{preview.artifact_id}</dd></div>
            <div><dt className="font-medium">Writing-style profile</dt><dd>{preview.profile_id}</dd></div>
            <div><dt className="font-medium">Source SHA-256 fingerprint</dt><dd>{preview.source_sha256}</dd></div>
            <div><dt className="font-medium">Analyze writing style</dt><dd>Allowed</dd></div>
            <div><dt className="font-medium">Apply writing style to generated content</dt><dd>{preview.style_use_allowed ? 'Allowed' : 'Not allowed'}</dd></div>
            <div><dt className="font-medium">Consent expires</dt><dd>{new Date(preview.expires_at).toLocaleString()}</dd></div>
            <div><dt className="font-medium">Confirmation deadline</dt><dd>{new Date(preview.approval_expires_at).toLocaleString()}</dd></div>
          </dl>
          {preview.status === 'pending' && expires > Date.now() ? (
            <>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                <span>I authored this document, reviewed the exact permitted uses above, and explicitly consent.</span>
              </label>
              <button
                type="button"
                disabled={!canConfirm}
                onClick={() => { void handleConfirm(); }}
                className="rounded-md border border-border px-4 py-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? 'Confirming…' : 'Confirm author consent'}
              </button>
            </>
          ) : (
            <p role="status">
              {preview.status === 'approved'
                ? 'This author decision is already approved.'
                : 'This author confirmation has expired.'}
            </p>
          )}
        </>
      )}
      {decision && (
        <p role="status">
          Author approval recorded. This is not a document-consent receipt.
          Document ingestion is not confirmed.
        </p>
      )}
    </section>
  );
}
