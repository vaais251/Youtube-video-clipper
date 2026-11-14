export function bound(value, min, max) { return Math.min(max, Math.max(min, value)); }

export function clock(ms, fractions = true) {
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor(total / 60) % 60;
  const seconds = String(total % 60).padStart(2, "0");
  const prefix = hours ? `${hours}:${String(minutes).padStart(2, "0")}` : String(minutes);
  return `${prefix}:${seconds}${fractions ? `.${String(ms % 1000).padStart(3, "0")}` : ""}`;
}

export function parseTime(raw) {
  const value = raw.trim();
  if (!/^(?:\d+:){0,2}\d+(?:\.\d{1,3})?$/.test(value)) return null;
  const parts = value.split(":").map(Number);
  if (parts.slice(1).some((part) => part >= 60)) return null;
  const ms = Math.round(parts.reduce((total, part) => total * 60 + part, 0) * 1000);
  return Number.isSafeInteger(ms) ? ms : null;
}

export function filenameError(value) {
  if (!value) return "";
  const stem = value.replace(/\.mp4$/i, "").trimEnd();
  if (!stem || /[<>:"/\\|?*\x00-\x1f]|\.$/.test(stem)) return 'Use a filename without < > : " / \\ | ? * or a trailing period.';
  if (/^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³])$/i.test(stem.split(".", 1)[0].trimEnd())) {
    return "That filename is reserved by Windows. Choose a different name.";
  }
  return stem.length > 251 ? "Shorten the clip filename." : "";
}
