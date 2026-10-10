export const getAlarmStatusLabel = (enabled: boolean): string => {
  return enabled ? 'Active' : 'Disabled';
};

export const parseAlarmDatetime = (isoStr: string) => {
  try {
    const d = new Date(isoStr);
    return isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
};
