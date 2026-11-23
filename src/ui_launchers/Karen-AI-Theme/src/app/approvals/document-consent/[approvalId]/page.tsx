'use client';

import { useParams } from 'next/navigation';

import { DocumentAuthorConsentConfirmation } from '@/components/consent/DocumentAuthorConsentConfirmation';

/** First-party source-specific author review, never a generic chat action. */
export default function DocumentAuthorConsentPage() {
  const params = useParams<{ approvalId: string }>();
  return <DocumentAuthorConsentConfirmation approvalId={params.approvalId} />;
}
