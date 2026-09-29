export const slugify = (name: string): string =>
  (name || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64);

export const humanSize = (n: number): string =>
  n >= 1e6
    ? `${(n / 1e6).toFixed(1)} MB`
    : n >= 1000
      ? `${Math.round(n / 1000)} KB`
      : `${n} B`;

// Relative time from a unix-seconds timestamp.
export const agoFromSeconds = (t: number): string => {
  const s = Math.round(Date.now() / 1000 - t);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
};

// Relative time from a Date (the "built …" readout under the viewport).
export const agoFromDate = (d: Date | null): string => {
  if (!d) return "—";
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  return s < 90
    ? "just now"
    : s < 5400
      ? `${Math.round(s / 60)} min ago`
      : s < 172800
        ? `${Math.round(s / 3600)} h ago`
        : `${Math.round(s / 86400)} days ago`;
};
