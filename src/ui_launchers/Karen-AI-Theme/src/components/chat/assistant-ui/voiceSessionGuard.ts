/** Prevent prior recordings and canceled requests from mutating active voice UI. */
export function isCurrentVoiceSession(
  mounted: boolean,
  activeGeneration: number,
  operationGeneration: number,
): boolean {
  return mounted && activeGeneration === operationGeneration;
}
