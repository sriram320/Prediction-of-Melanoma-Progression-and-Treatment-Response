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
