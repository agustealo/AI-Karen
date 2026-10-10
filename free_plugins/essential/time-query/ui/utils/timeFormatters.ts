export const formatMsToStopwatch = (ms: number): string => {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const centiseconds = Math.floor((ms % 1000) / 10);
  
  return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}.${centiseconds.toString().padStart(2, '0')}`;
};

export const offsetToLabel = (offsetSeconds: number): string => {
  const sign = offsetSeconds >= 0 ? '+' : '-';
  const hours = Math.floor(Math.abs(offsetSeconds) / 3600);
  const mins = Math.floor((Math.abs(offsetSeconds) % 3600) / 60);
  return `UTC${sign}${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}`;
};
