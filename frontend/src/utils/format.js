const dateFmt = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
});

export function formatDate(value) {
  if (!value) return "–";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "–" : dateFmt.format(d);
}

export function formatDateTime(value) {
  if (!value) return "–";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "–" : dateTimeFmt.format(d);
}

export function errorMessage(err, fallback = "Something went wrong. Please try again.") {
  return err?.detail || err?.message || fallback;
}

/** Maps a 422 response's `errors[]` to {field: message} for inline form errors. */
export function fieldErrors(err) {
  const out = {};
  for (const e of err?.errors || []) {
    const field = String(e.field || "").split(".").pop();
    if (field && !out[field]) out[field] = e.message.replace(/^Value error, /, "");
  }
  return out;
}

export function todayISO() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}
