// Utility to list common timezones or format them nicely
export const COMMON_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Paris",
  "Africa/Lusaka",
  "Asia/Tokyo",
  "Asia/Kolkata",
  "Australia/Sydney"
];

export const formatTimezoneName = (tz: string): string => {
  return tz.split('/').pop()?.replace(/_/g, ' ') || tz;
};
