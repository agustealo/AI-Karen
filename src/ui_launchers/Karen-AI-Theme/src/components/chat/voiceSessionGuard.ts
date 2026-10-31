/** Prevent prior recordings and canceled requests from mutating active voice UI. */
export function isCurrentVoiceSession(
  mounted: boolean,
  activeGeneration: number,
  operationGeneration: number,
): boolean {
  return mounted && activeGeneration === operationGeneration;
}

/** Enforce cancellation before upload and before draft mutation. */
export function canCommitVoiceResult(
  mounted: boolean,
  activeGeneration: number,
  operationGeneration: number,
  aborted: boolean,
): boolean {
  return isCurrentVoiceSession(mounted, activeGeneration, operationGeneration) && !aborted;
}
