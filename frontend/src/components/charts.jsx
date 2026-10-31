// Shared chart pieces (Recharts). Marks follow one spec everywhere: 2px lines, r=4 markers with a 2px surface ring,
// columns at most 24px wide with a 4px rounded end, hairline solid grid, text in text tokens (never series colour).
// Colours come from the CSS tokens in styles/index.css so the charts always match the theme.
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis,
  YAxis,
} from "recharts";
import { RISK_CATEGORIES, RISK_THRESHOLDS } from "../utils/clinical.js";
import { formatDate } from "../utils/format.js";

const tokenCache = {};
export function token(name) {
  if (!(name in tokenCache)) {
    tokenCache[name] = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim() || "currentColor";
  }
  return tokenCache[name];
}

const axisProps = () => ({
  stroke: token("border"),
  tick: { fill: token("text-faint"), fontSize: 11 },
  tickLine: false,
});

function grid() {
  return <CartesianGrid stroke={token("border")} strokeWidth={1} vertical={false} />;
}

/** The tooltip card. `rows` is [[label, value], ...]. */
export function TooltipCard({ title, rows = [], note }) {
  return (
    <div className="chart-tooltip">
      {title && <div className="chart-tooltip__title">{title}</div>}
      {rows.map(([k, v]) => (
        <div key={k} className="chart-tooltip__row"><span>{k}</span><strong>{v}</strong></div>
      ))}
      {note && <div className="chart-tooltip__note">{note}</div>}
    </div>
  );
}

const MONTH = new Intl.DateTimeFormat("en-IN", { month: "short" });
const MONTH_YEAR = new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" });
const monthDate = (key) => new Date(`${key}-01T00:00:00`);
const monthTick = (key, i) => {
  const d = monthDate(key);
  return i === 0 || d.getMonth() === 0 ? `${MONTH.format(d)} ${String(d.getFullYear()).slice(2)}` : MONTH.format(d);
};

/** One count per month as columns (a single series, so the card title names it and there is no legend). */
export function MonthlyColumns({ data, dataKey, unit, id }) {
  const rows = data.map((m, i) => ({ ...m, tick: monthTick(m.month, i) }));
  return (
    <div className="chart chart--sm" id={id}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 4, bottom: 0, left: -18 }} barCategoryGap="22%">
          {grid()}
          <XAxis dataKey="tick" {...axisProps()} interval="preserveStartEnd" minTickGap={6} />
          <YAxis allowDecimals={false} {...axisProps()} axisLine={false} width={44} />
          <Tooltip cursor={{ fill: token("surface-hover") }} isAnimationActive={false}
            content={({ active, payload }) => (active && payload?.length ? (
              <TooltipCard title={MONTH_YEAR.format(monthDate(payload[0].payload.month))}
                rows={[[unit, payload[0].value]]} />
            ) : null)} />
          <Bar dataKey={dataKey} fill={token("accent")} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

const ts = (isoDate) => new Date(`${isoDate}T00:00:00`).getTime();
const shortDate = (t) => formatDate(new Date(t));

function timeDomain(xs) {
  const min = Math.min(...xs);
  const max = Math.max(...xs);
  const pad = Math.max((max - min) * 0.06, 20 * 86_400_000);
  return [min - pad, max + pad];
}

/**
 * Risk score of a lesion over its visits (the newest analysis of each visit). The category bands sit behind the
 * line; visits whose newest result was a referral (no score) are marked with a labelled vertical line instead.
 */
export function RiskTrendChart({ history, id }) {
  const byVisit = new Map();
  for (const p of history) {
    if (p.is_baseline) continue;
    const prev = byVisit.get(p.visit_id);
    byVisit.set(p.visit_id, { latest: p, count: (prev?.count || 0) + 1 });
  }
  const entries = [...byVisit.values()].sort((a, b) => a.latest.visit_date.localeCompare(b.latest.visit_date));
  const points = entries.filter((e) => !e.latest.referral_flag && e.latest.risk_score != null)
    .map((e) => ({ x: ts(e.latest.visit_date), score: e.latest.risk_score, p: e.latest, count: e.count }));
  const referrals = entries.filter((e) => e.latest.referral_flag).map((e) => ts(e.latest.visit_date));
  if (!points.length && !referrals.length) return null;
  const xs = [...points.map((d) => d.x), ...referrals];
  const bands = [
    [0, RISK_THRESHOLDS[0], "routine", "Routine"],
    [RISK_THRESHOLDS[0], RISK_THRESHOLDS[1], "shortened", "Shortened interval"],
    [RISK_THRESHOLDS[1], 1, "referral", "Specialist referral"],
  ];

  return (
    <div className="chart chart--md" id={id} role="img"
      aria-label={`Risk score at ${points.length} analysed visit${points.length === 1 ? "" : "s"}`
        + (points.length ? `, latest ${points[points.length - 1].score.toFixed(2)}` : "")
        + (referrals.length ? `; ${referrals.length} referred without a score` : "")}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 18, right: 16, bottom: 0, left: -12 }}>
          {bands.map(([y1, y2, tone, label]) => (
            <ReferenceArea key={tone} y1={y1} y2={y2} fill={token(tone)} fillOpacity={0.07} stroke="none"
              label={{ value: label, position: "insideTopLeft", fill: token("text-faint"), fontSize: 11 }} />
          ))}
          {grid()}
          <XAxis dataKey="x" type="number" scale="time" domain={timeDomain(xs)} ticks={[...new Set(xs)].sort()}
            tickFormatter={shortDate} {...axisProps()} />
          <YAxis domain={[0, 1]} ticks={[0, ...RISK_THRESHOLDS, 1]} {...axisProps()} axisLine={false} width={48} />
          {referrals.map((x) => (
            <ReferenceLine key={x} x={x} stroke={token("referral")} strokeWidth={2}
              label={{ value: "Referred", position: "top", fill: token("text-muted"), fontSize: 11 }} />
          ))}
          <Tooltip isAnimationActive={false} cursor={{ stroke: token("border-strong"), strokeWidth: 1 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const { p, count } = payload[0].payload;
              const rows = [["Risk score", p.risk_score.toFixed(2)], ["AI category", RISK_CATEGORIES[p.risk_category]?.label]];
              if (p.uncertainty_score != null) rows.push(["Uncertainty", p.uncertainty_score.toFixed(2)]);
              rows.push(["Doctor", p.final_category
                ? `${p.review_decision === "confirmed" ? "Confirmed" : "Changed to"} ${RISK_CATEGORIES[p.final_category].label.toLowerCase()}`
                : "Not reviewed"]);
              return <TooltipCard title={`Visit of ${formatDate(p.visit_date)}`} rows={rows}
                note={count > 1 ? `Newest of ${count} analyses of this visit` : undefined} />;
            }} />
          <Line dataKey="score" stroke={token("accent")} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
            isAnimationActive={false}
            dot={{ r: 4, fill: token("accent"), stroke: token("surface-solid"), strokeWidth: 2 }}
            activeDot={{ r: 6, fill: token("accent"), stroke: token("surface-solid"), strokeWidth: 2 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** A small single-measure line chart (one of a row of small multiples, each with its own axis). */
export function MiniLine({ data, format, id, label }) {
  const xs = data.map((d) => d.x);
  return (
    <div className="chart chart--xs" id={id} role="img"
      aria-label={`${label}: ${data.map((d) => `${shortDate(d.x)} ${format(d.value)}`).join(", ")}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -18 }}>
          {grid()}
          <XAxis dataKey="x" type="number" scale="time" domain={timeDomain(xs)} ticks={[xs[0], xs[xs.length - 1]]}
            tickFormatter={shortDate} {...axisProps()} />
          <YAxis domain={["auto", "auto"]} tickCount={3} tickFormatter={(v) => format(v)} {...axisProps()}
            axisLine={false} width={50} />
          <Tooltip isAnimationActive={false} cursor={{ stroke: token("border-strong"), strokeWidth: 1 }}
            content={({ active, payload }) => (active && payload?.length ? (
              <TooltipCard title={formatDate(new Date(payload[0].payload.x))} rows={[[label, format(payload[0].value)]]} />
            ) : null)} />
          <Line dataKey="value" stroke={token("accent")} strokeWidth={2} isAnimationActive={false}
            dot={{ r: 4, fill: token("accent"), stroke: token("surface-solid"), strokeWidth: 2 }}
            activeDot={{ r: 6, fill: token("accent"), stroke: token("surface-solid"), strokeWidth: 2 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export { ts as dateToTime };
