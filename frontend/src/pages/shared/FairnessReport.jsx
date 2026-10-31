import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get, qs } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import Icon from "../../components/Icon.jsx";
import PageLoading from "../../components/PageLoading.jsx";
import { Alert, Badge, Button, PageHeader, Select, StatCard, TextInput } from "../../components/ui.jsx";
import { fitzpatrickShort, siteLabel } from "../../utils/clinical.js";
import { errorMessage, formatDateTime, todayISO } from "../../utils/format.js";

const DIMENSIONS = [
  { key: "fitzpatrick_type", label: "Skin type", value: (v) => fitzpatrickShort(Number(v)) },
  { key: "anatomical_site", label: "Body site", value: siteLabel },
  { key: "device_model", label: "Device", value: (v) => v },
  { key: "illumination", label: "Illumination", value: (v) => v },
];

function daysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

const PRESETS = [
  { id: "90d", label: "Last 90 days", from: () => daysAgo(90) },
  { id: "12m", label: "Last 12 months", from: () => daysAgo(365) },
  { id: "all", label: "All time", from: () => "" },
];

const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const groupLabel = (dim, v) => (v == null ? "Not recorded" : dim.value(v));

/** A rate as text plus a bar, with a tick at the all-results rate so a subgroup's distance from it is visible. */
function RateCell({ rate, num, den, reference }) {
  if (rate == null) return <span className="faint">–</span>;
  return (
    <div className="rate-cell" title={reference != null ? `All results: ${pct(reference)}` : undefined}>
      <span className="rate-cell__track" aria-hidden="true">
        <span className="rate-cell__bar" style={{ width: `${Math.max(rate * 100, rate > 0 ? 2 : 0)}%` }} />
        {reference != null && <span className="rate-cell__ref" style={{ left: `${reference * 100}%` }} />}
      </span>
      <span className="rate-cell__value">{pct(rate)} <span className="faint">({num}/{den})</span></span>
    </div>
  );
}

const MIX = [
  { key: "routine_n", tone: "routine", label: "Routine" },
  { key: "shortened_n", tone: "shortened", label: "Shortened interval" },
  { key: "specialist_n", tone: "referral", label: "Specialist referral" },
];

function MixBar({ row }) {
  if (!row.scored_n) return <span className="faint">–</span>;
  const text = MIX.map((m) => `${m.label} ${row[m.key]}`).join(", ");
  return (
    <span className="mix-bar" role="img" aria-label={text} title={text}>
      {MIX.filter((m) => row[m.key] > 0).map((m) => (
        <span key={m.key} className={`mix-bar__seg mix-bar__seg--${m.tone}`} style={{ flexGrow: row[m.key] }} />
      ))}
    </span>
  );
}

function AccuracyCell({ ai, after, positive }) {
  const [hit, total] = positive ? [ai.tp, ai.tp + ai.fn] : [ai.tn, ai.tn + ai.fp];
  if (!total) return <span className="faint">–</span>;
  const [hitR, totalR] = positive ? [after.tp, after.tp + after.fn] : [after.tn, after.tn + after.fp];
  return (
    <div className="acc-cell">
      <div>AI {pct(hit / total)} <span className="faint">({hit}/{total})</span></div>
      <div className="faint">After review {totalR ? `${pct(hitR / totalR)} (${hitR}/${totalR})` : "–"}</div>
    </div>
  );
}

function SubgroupTable({ dim, rows, overall, minGroup }) {
  return (
    <div className="table-wrap">
      <table className="table fairness-table" id={`fairness-table-${dim.key}`}>
        <caption className="visually-hidden">
          {`Results by ${dim.label.toLowerCase()}. Bars show each group's rate; the tick marks the rate across all results.`}
        </caption>
        <thead>
          <tr>
            <th scope="col">{dim.label}</th>
            <th scope="col" className="num">Results</th>
            <th scope="col">Referred</th>
            <th scope="col">Category changed by doctor</th>
            <th scope="col" className="num">Mean risk</th>
            <th scope="col">AI categories</th>
            <th scope="col">Sensitivity</th>
            <th scope="col">Specificity</th>
          </tr>
        </thead>
        <tbody>
          {[{ ...overall, isOverall: true }, ...rows].map((r) => (
            <tr key={r.isOverall ? "__all" : String(r.value)} className={[r.isOverall && "fairness-table__overall",
              !r.isOverall && r.small_sample && "fairness-table__small"].filter(Boolean).join(" ")}>
              <th scope="row">
                {r.isOverall ? "All results" : groupLabel(dim, r.value)}
                {!r.isOverall && r.small_sample && (
                  <div><Badge kind="warning">Fewer than {minGroup}: too few to compare</Badge></div>
                )}
              </th>
              <td className="num">{r.n}</td>
              <td><RateCell rate={r.referral_rate} num={r.referral_n} den={r.n}
                reference={r.isOverall ? null : overall.referral_rate} /></td>
              <td><RateCell rate={r.override_rate} num={r.override_n} den={r.reviewed_scored_n}
                reference={r.isOverall ? null : overall.override_rate} /></td>
              <td className="num">{r.mean_risk == null ? "–" : r.mean_risk.toFixed(2)}</td>
              <td><MixBar row={r} /></td>
              <td><AccuracyCell ai={r.ai} after={r.after_review} positive /></td>
              <td><AccuracyCell ai={r.ai} after={r.after_review} positive={false} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Calibration({ bins }) {
  const known = bins.reduce((n, b) => n + b.n, 0);
  return (
    <section className="card" aria-labelledby="calibration-title">
      <h2 id="calibration-title" className="card__title">Calibration against histopathology</h2>
      {known === 0 ? (
        <p className="muted" style={{ marginTop: 8 }}>
          No scored result in this period has a histopathology result yet. Record biopsy or excision results on the
          lesion page (Treatments) to fill in calibration, sensitivity and specificity.
        </p>
      ) : (
        <>
          <p className="faint" style={{ fontSize: "0.85rem", margin: "6px 0 12px" }}>
            In a well-calibrated model the observed melanoma rate in each band is close to its mean predicted risk.
          </p>
          <div className="table-wrap">
            <table className="table table--compact" id="calibration-table">
              <thead><tr><th>Risk score band</th><th className="num">Results</th><th className="num">Mean predicted risk</th><th className="num">Melanoma on histopathology</th></tr></thead>
              <tbody>
                {bins.map((b) => (
                  <tr key={b.lower}>
                    <td>{b.lower.toFixed(1)} to {b.upper.toFixed(1)}</td>
                    <td className="num">{b.n}</td>
                    <td className="num">{b.mean_risk == null ? "–" : b.mean_risk.toFixed(2)}</td>
                    <td className="num">{pct(b.observed_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function toCsv(report) {
  const head = ["dimension", "group", "results", "referred", "referral_rate", "reviewed_with_category", "changed",
    "override_rate", "mean_risk", "routine", "shortened_interval", "specialist_referral", "with_histopathology",
    "melanoma", "ai_sensitivity", "ai_specificity", "after_review_sensitivity", "after_review_specificity"];
  const line = (dimension, group, r) => [dimension, group, r.n, r.referral_n, r.referral_rate, r.reviewed_scored_n,
    r.override_n, r.override_rate, r.mean_risk, r.routine_n, r.shortened_n, r.specialist_n, r.outcome_n, r.melanoma_n,
    r.ai.sensitivity, r.ai.specificity, r.after_review.sensitivity, r.after_review.specificity];
  const rows = [line("all", "all", report.overall)];
  for (const d of report.dimensions) {
    const dim = DIMENSIONS.find((x) => x.key === d.key);
    for (const r of d.rows) rows.push(line(d.key, groupLabel(dim, r.value), r));
  }
  const cell = (v) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  return [head, ...rows].map((r) => r.map(cell).join(",")).join("\n");
}

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function FairnessReport() {
  const { user } = useAuth();
  const platform = user.role === "super_admin";
  const [preset, setPreset] = useState("12m");
  const [from, setFrom] = useState(PRESETS[1].from());
  const [to, setTo] = useState("");
  const [hospitalId, setHospitalId] = useState("");
  const [dimKey, setDimKey] = useState(DIMENSIONS[0].key);

  const hospitals = useQuery({
    queryKey: ["admin", "hospitals", "all"],
    queryFn: () => get("/admin/hospitals?page_size=100"),
    enabled: platform,
  });
  const params = { from, to, hospital_id: platform ? hospitalId : "" };
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["fairness", params],
    queryFn: () => get(`/reports/subgroup-performance${qs(params)}`),
  });

  const choosePreset = (p) => { setPreset(p.id); setFrom(p.from()); setTo(""); };
  const dim = DIMENSIONS.find((d) => d.key === dimKey);
  const rows = data?.dimensions.find((d) => d.key === dimKey)?.rows || [];
  const o = data?.overall;
  const scope = platform ? (data?.hospital_name || "All hospitals") : user.hospital?.name;

  return (
    <>
      <PageHeader eyebrow={scope} title="Fairness report"
        subtitle="How the AI's results and doctors' changes compare across skin types, body sites, devices and lighting."
        actions={data && (
          <Button variant="secondary" id="fairness-export-btn"
            onClick={() => download(`fairness-${todayISO()}.csv`, toCsv(data))}>
            <Icon name="download" size={16} /> Export CSV
          </Button>
        )} />

      <div className="stack stack--lg">
        <div className="card filter-bar" role="search" aria-label="Report period">
          <div className="row" style={{ gap: 6 }}>
            {PRESETS.map((p) => (
              <Button key={p.id} size="sm" variant={preset === p.id ? "primary" : "ghost"} id={`fairness-preset-${p.id}`}
                aria-pressed={preset === p.id} onClick={() => choosePreset(p)}>{p.label}</Button>
            ))}
          </div>
          <div className="filter-bar__fields">
            <TextInput id="fairness-from" label="From" type="date" value={from} max={to || todayISO()}
              onChange={(e) => { setPreset(""); setFrom(e.target.value); }} />
            <TextInput id="fairness-to" label="To" type="date" value={to} min={from || undefined} max={todayISO()}
              onChange={(e) => { setPreset(""); setTo(e.target.value); }} />
            {platform && (
              <Select id="fairness-hospital" label="Hospital" value={hospitalId} onChange={(e) => setHospitalId(e.target.value)}
                options={[{ value: "", label: "All hospitals" },
                  ...(hospitals.data?.items || []).map((h) => ({ value: h.id, label: `${h.name} (${h.code})` }))]} />
            )}
          </div>
        </div>

        {isLoading && <PageLoading />}
        {isError && <Alert kind="error">{errorMessage(error)}</Alert>}
        {data && (
          <>
            {data.any_mock && (
              <Alert kind="warning">
                These results come from the <strong>mock model</strong>. The page works end to end, but the numbers say
                nothing about how a real model treats different groups.
              </Alert>
            )}
            {o.n === 0 ? (
              <div className="card"><p className="muted">No AI results with a score or referral in this period.</p></div>
            ) : (
              <>
                <div className="stat-grid">
                  <StatCard label="Lesions with a result" value={o.n} note="Each lesion's newest result in the period" />
                  <StatCard label="Referred without a category" value={pct(o.referral_rate)} note={`${o.referral_n} of ${o.n}`} />
                  <StatCard label="Category changed by doctor" value={pct(o.override_rate)}
                    note={`${o.override_n} of ${o.reviewed_scored_n} reviewed`} />
                  <StatCard label="Mean risk score" value={o.mean_risk == null ? "–" : o.mean_risk.toFixed(2)}
                    note={`${o.scored_n} scored results`} />
                  <StatCard label="With histopathology" value={o.outcome_n} note={`${o.melanoma_n} melanoma`} />
                  <StatCard label="AI sensitivity / specificity"
                    value={`${pct(o.ai.sensitivity)} / ${pct(o.ai.specificity)}`} note="Against histopathology" />
                </div>

                <section className="card card--flush" aria-labelledby="fairness-groups-title">
                  <div className="card__header" style={{ padding: "18px 20px 0" }}>
                    <h2 id="fairness-groups-title" className="card__title">By subgroup</h2>
                    <div className="mix-legend" aria-label="AI category colours">
                      {MIX.map((m) => (
                        <span key={m.key} className="mix-legend__item">
                          <span className={`mix-legend__swatch mix-bar__seg--${m.tone}`} />{m.label}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="tabs" role="tablist" aria-label="Group results by" style={{ padding: "0 20px" }}>
                    {DIMENSIONS.map((d) => (
                      <button key={d.key} type="button" role="tab" className="tabs__btn" aria-selected={dimKey === d.key}
                        aria-controls="fairness-panel" id={`fairness-tab-${d.key}`} onClick={() => setDimKey(d.key)}>
                        {d.label}
                      </button>
                    ))}
                  </div>
                  <div role="tabpanel" id="fairness-panel" aria-labelledby={`fairness-tab-${dimKey}`}>
                    <SubgroupTable dim={dim} rows={rows} overall={o} minGroup={data.min_group_size} />
                  </div>
                </section>
              </>
            )}

            <Calibration bins={data.calibration} />

            <details className="card definitions" id="fairness-definitions">
              <summary>How these figures are calculated</summary>
              <ul>
                <li><strong>Result:</strong> each lesion counts once, with its newest AI result from the period. Baselines
                  (a single visit) have no score and are left out.</li>
                <li><strong>Referred:</strong> the model gave no category and sent the case to a dermatologist (low
                  confidence, poor images or a model error).</li>
                <li><strong>Category changed by doctor:</strong> share of reviewed results with an AI category where the
                  doctor chose a different one. Referrals are not counted: they have no AI category to change.</li>
                <li><strong>Sensitivity / specificity:</strong> for lesions with a histopathology result (recorded on a
                  biopsy or excision), the newest result from a visit on or before the procedure. A result counts as
                  flagged when it is anything other than routine monitoring. "After review" uses the doctor's category.</li>
                <li><strong>Small groups:</strong> groups with fewer than {data.min_group_size} results are shown, but a
                  difference there is likely to be chance.</li>
                <li>Skin type is the Fitzpatrick type recorded on the patient; device and illumination come from the
                  analysed visit. Figures never include names or record numbers.</li>
              </ul>
              <p className="faint">Generated {formatDateTime(data.generated_at)}
                {data.models.length > 0 && ` · ${data.models.map((m) => `${m.name} ${m.version}`).join(", ")}`}</p>
            </details>
          </>
        )}
      </div>
    </>
  );
}
