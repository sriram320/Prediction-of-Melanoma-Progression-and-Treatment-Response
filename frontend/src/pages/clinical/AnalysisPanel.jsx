import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../api/client.js";
import { ROLE_LABELS } from "../../auth/roles.js";
import { dateToTime, MiniLine, RiskTrendChart } from "../../components/charts.jsx";
import Icon from "../../components/Icon.jsx";
import ImageViewer from "../../components/ImageViewer.jsx";
import SecureImage from "../../components/SecureImage.jsx";
import { Alert } from "../../components/ui.jsx";
import {
  featureLabel, formatFeature, REASON_CODES, RISK_CATEGORIES, RISK_THRESHOLDS,
} from "../../utils/clinical.js";
import { actionLabel } from "../../utils/audit.js";
import { formatDate, formatDateTime } from "../../utils/format.js";
import ReviewBox from "./ReviewBox.jsx";

const roleLabel = (r) => ROLE_LABELS[r] || r;

/** Risk score on a 0-1 track, with the category thresholds marked. Value and category are also given as text. */
function RiskMeter({ score, tone }) {
  return (
    <div className="risk-meter" role="img"
      aria-label={`Risk score ${score.toFixed(2)} on a scale of 0 to 1; thresholds at ${RISK_THRESHOLDS.join(" and ")}`}>
      <div className={`risk-meter__track risk-meter__track--${tone}`}>
        <div className={`risk-meter__fill risk-meter__fill--${tone}`} style={{ width: `${Math.max(score * 100, 2)}%` }} />
        {RISK_THRESHOLDS.map((t) => <span key={t} className="risk-meter__tick" style={{ left: `${t * 100}%` }} />)}
      </div>
      <div className="risk-meter__scale" aria-hidden="true">
        <span>0</span><span style={{ left: "35%" }}>0.35</span><span style={{ left: "65%" }}>0.65</span><span>1</span>
      </div>
    </div>
  );
}

function Verdict({ p }) {
  if (p.referral_flag) {
    return (
      <div className="verdict verdict--referral" role="status">
        <Icon name="alert" size={22} />
        <div>
          <div className="verdict__title">Needs dermatologist review</div>
          <p>The model is not confident enough to give a category, so it gives none.</p>
          <ul className="verdict__reasons">
            {p.reason_codes.map((r) => <li key={r}>{REASON_CODES[r] || r}</li>)}
          </ul>
        </div>
      </div>
    );
  }
  if (p.is_baseline) {
    return (
      <div className="verdict verdict--baseline" role="status">
        <Icon name="info" size={22} />
        <div>
          <div className="verdict__title">Baseline recorded</div>
          <p>A risk estimate needs scans from a second visit to compare with.</p>
        </div>
      </div>
    );
  }
  const cat = RISK_CATEGORIES[p.risk_category];
  return (
    <div className={`verdict verdict--${cat.tone}`} role="status">
      <Icon name={cat.icon} size={22} />
      <div style={{ flex: 1 }}>
        <div className="verdict__title">{cat.label}</div>
        <div className="row" style={{ gap: 18, marginTop: 4 }}>
          <span>Risk score <strong>{p.risk_score.toFixed(2)}</strong></span>
          {p.uncertainty_score != null && <span>Uncertainty <strong>{p.uncertainty_score.toFixed(2)}</strong></span>}
          {p.change_score != null && <span>Change <strong>{p.change_score.toFixed(2)}</strong></span>}
        </div>
        <RiskMeter score={p.risk_score} tone={cat.tone} />
      </div>
    </div>
  );
}

function Measurements({ features, attention }) {
  if (!features.length) return null;
  const keys = [...new Set(features.flatMap((f) => Object.keys(f.features)))];
  return (
    <div className="table-wrap">
      <table className="table table--compact">
        <caption className="visually-hidden">Measurements per visit and the model's attention to each visit</caption>
        <thead>
          <tr>
            <th>Visit</th>
            {keys.map((k) => <th key={k} className="num">{featureLabel(k)}</th>)}
            <th>Model attention</th>
          </tr>
        </thead>
        <tbody>
          {features.map((f) => {
            const weight = attention[f.visit_id] ?? 0;
            return (
              <tr key={f.visit_id}>
                <td>{formatDate(f.visit_date)}</td>
                {keys.map((k) => <td key={k} className="num">{formatFeature(k, f.features[k])}</td>)}
                <td>
                  <div className="bar-cell" title={`${Math.round(weight * 100)}% of the model's attention`}>
                    <span className="bar-cell__track"><span className="bar-cell__bar" style={{ width: `${weight * 100}%` }} /></span>
                    <span className="bar-cell__value">{Math.round(weight * 100)}%</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Risk score per analysed visit, plus each measurement over the visits as small multiples (one axis each). */
function Trends({ prediction: p, lesionId }) {
  const { data: history } = useQuery({
    queryKey: ["lesion", lesionId, "timeline", "predictions", p.id],
    queryFn: () => get(`/lesions/${lesionId}/predictions`),
  });
  const keys = [...new Set(p.visit_features.flatMap((f) => Object.keys(f.features)))];
  const series = keys.map((k) => ({
    key: k,
    data: p.visit_features.filter((f) => f.features[k] != null)
      .map((f) => ({ x: dateToTime(f.visit_date), value: f.features[k] })),
  })).filter((s) => s.data.length >= 2);
  const scored = (history || []).filter((h) => !h.is_baseline && !h.referral_flag).length;
  if (!series.length && !history?.some((h) => !h.is_baseline)) return null;
  return (
    <div className="stack stack--sm">
      <h3 className="analysis-panel__h">Trend</h3>
      {history && <RiskTrendChart history={history} id="risk-trend-chart" />}
      {history && scored === 1 && (
        <p className="faint" style={{ fontSize: "0.82rem" }}>One scored result so far. The trend fills in as later visits are analysed.</p>
      )}
      {series.length > 0 && (
        <div className="mini-grid" aria-label="Measurements over the visits">
          {series.map((s) => (
            <figure key={s.key} className="mini-chart">
              <figcaption className="mini-chart__title">{featureLabel(s.key)}</figcaption>
              <MiniLine data={s.data} label={featureLabel(s.key)} format={(v) => formatFeature(s.key, v)}
                id={`trend-${s.key}`} />
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}

/** Everything recorded about this result, loaded when opened. */
function AuditTrail({ predictionId }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["audit", "prediction", predictionId],
    queryFn: () => get(`/audit/${predictionId}`),
    enabled: open,
  });
  return (
    <details className="audit-trail" onToggle={(e) => setOpen(e.currentTarget.open)} id="analysis-audit-trail">
      <summary>History of this result</summary>
      {isLoading && <p className="faint">Loading…</p>}
      {isError && <p className="faint">The history could not be loaded.</p>}
      {data && (
        <ol className="audit-trail__list">
          {data.map((e) => (
            <li key={e.id}>
              <span className="faint">{formatDateTime(e.occurred_at)}</span>
              <span>{actionLabel(e.action)}</span>
              <span className="muted">{e.actor_name || (e.role ? roleLabel(e.role) : "System")}</span>
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}

export default function AnalysisPanel({ prediction: p, lesionId, onReviewed }) {
  const [viewing, setViewing] = useState(false);
  const { data: exp } = useQuery({
    queryKey: ["prediction", p.id, "explanation"],
    queryFn: () => get(`/predictions/${p.id}/explanation`),
  });
  const maps = exp ? [
    exp.difference_map_file_id && { fileId: exp.difference_map_file_id, caption: "Difference map: colour change, first vs latest visit" },
    exp.saliency_file_id && { fileId: exp.saliency_file_id, caption: "Highlight map: regions that drove the result" },
  ].filter(Boolean) : [];

  return (
    <section className="card analysis-panel" aria-labelledby="analysis-title">
      {p.model.is_mock && <div className="analysis-panel__mock">MOCK MODEL — NOT FOR CLINICAL USE</div>}
      <div className="card__header">
        <div>
          <h2 id="analysis-title" className="card__title">AI analysis</h2>
          <div className="faint" style={{ fontSize: "0.82rem" }}>
            Up to the visit of {formatDate(p.visit_date)} · {p.model.name} {p.model.version} · {formatDateTime(p.created_at)}
            {p.inference_ms != null && ` · ${(p.inference_ms / 1000).toFixed(1)} s`}
          </div>
        </div>
        <span className="badge">{p.reviewed ? "Reviewed" : "Awaiting doctor review"}</span>
      </div>

      <div className="stack">
        <Verdict p={p} />
        {p.model_error && <p className="faint" style={{ fontSize: "0.82rem" }}>Technical detail: {p.model_error}</p>}
        {exp?.registration_warning && (
          <Alert kind="warning">The visits could not be aligned reliably. Compare the images directly before relying on the change measurements.</Alert>
        )}

        {exp?.change_summary?.length > 0 && (
          <div>
            <h3 className="analysis-panel__h">What changed</h3>
            <ul className="analysis-panel__summary">{exp.change_summary.map((s) => <li key={s}>{s}</li>)}</ul>
          </div>
        )}

        <Trends prediction={p} lesionId={lesionId} />

        {p.visit_features.length > 0 && (
          <div>
            <h3 className="analysis-panel__h">Measurements per visit</h3>
            <Measurements features={p.visit_features} attention={exp?.attention_weights || {}} />
          </div>
        )}

        {maps.length > 0 && (
          <div>
            <h3 className="analysis-panel__h">Explanation maps</h3>
            <div className="map-grid">
              {maps.map((m) => (
                <button key={m.fileId} type="button" className="map-tile" id={`map-${m.fileId}`} onClick={() => setViewing(true)}>
                  <span className="thumb"><SecureImage fileId={m.fileId} size={512} alt="" /></span>
                  <span className="map-tile__caption">{m.caption}</span>
                </button>
              ))}
            </div>
            {exp && !exp.saliency_passed_check && (
              <p className="faint" style={{ fontSize: "0.82rem", marginTop: 8 }}>The highlight map failed its sanity check; do not rely on it.</p>
            )}
          </div>
        )}

        <ReviewBox key={p.id} prediction={p} lesionId={lesionId} onReviewed={onReviewed} />
        <AuditTrail key={`trail-${p.id}-${p.latest_review?.id || ""}`} predictionId={p.id} />
        <p className="faint" style={{ fontSize: "0.82rem" }}>
          AI decision support only. The final assessment is made by the reviewing and signing doctor.
        </p>
      </div>

      {viewing && <ImageViewer id="maps-viewer" title="Explanation maps" items={maps} onClose={() => setViewing(false)} />}
    </section>
  );
}
