const relative = new Intl.RelativeTimeFormat("es", { numeric: "auto" });

/** "hace 5 min", "ayer"... para la lista de conversaciones. */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const diffSec = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(diffSec);
  if (abs < 60) return "ahora";
  if (abs < 3600) return relative.format(Math.round(diffSec / 60), "minute");
  if (abs < 86_400) return relative.format(Math.round(diffSec / 3600), "hour");
  if (abs < 86_400 * 30) return relative.format(Math.round(diffSec / 86_400), "day");
  return new Date(iso).toLocaleDateString("es");
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "";
  const gb = bytes / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(bytes / 1024 ** 2)} MB`;
}
