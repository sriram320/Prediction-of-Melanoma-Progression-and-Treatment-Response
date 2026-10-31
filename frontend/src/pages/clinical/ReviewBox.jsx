import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../../api/client.js";
import Icon from "../../components/Icon.jsx";
import { Alert, Badge, Button, TextArea } from "../../components/ui.jsx";
import { REPORT_STATUS, RISK_CATEGORIES } from "../../utils/clinical.js";
import { errorMessage, formatDateTime } from "../../utils/format.js";
import { useCan, usePortalBase } from "./portal.js";

/** Doctor review of an AI result (human in the loop) and the step to the report. */
export default function ReviewBox({ prediction: p, lesionId, onReviewed }) {
  const can = useCan();
  const base = usePortalBase();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const aiCategory = p.referral_flag || p.is_baseline ? null : p.risk_category;
  const review = p.latest_review;
  const [editing, setEditing] = useState(!review && can.review);
  const [category, setCategory] = useState(review?.final_category || aiCategory || "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const needsReason = !aiCategory || category !== aiCategory;

  const reportsQ = useQuery({
    queryKey: ["lesion", lesionId, "reports"],
    queryFn: () => get(`/reports?lesion_id=${lesionId}&page_size=50`),
  });
  const forThisResult = (reportsQ.data?.items || []).filter((r) => r.prediction_id === p.id);
  const openDraft = forThisResult.find((r) => r.status === "draft" || r.status === "pending_review");

  const save = useMutation({
    mutationFn: () => post(`/predictions/${p.id}/review`, { final_category: category, reason: reason.trim() || null }),
    onSuccess: () => {
      setEditing(false);
      setReason("");
      onReviewed();
    },
    onError: (err) => setError(errorMessage(err)),
  });
  const createReport = useMutation({
    mutationFn: () => post("/reports", { lesion_id: lesionId, prediction_id: p.id }),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ["lesion", lesionId, "reports"] });
      navigate(`${base}/reports/${r.id}`);
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <div className="review-box" aria-labelledby="review-title">
      <h3 id="review-title" className="analysis-panel__h">Doctor review</h3>
      {review && !editing && (
        <div className="review-box__done">
          <Badge kind={review.decision === "confirmed" ? "success" : "warning"} dot>
            {review.decision === "confirmed" ? "AI result confirmed" : "AI result overridden"}
          </Badge>
          <div className="review-box__category">{RISK_CATEGORIES[review.final_category].label}</div>
          {review.reason && <p className="muted">“{review.reason}”</p>}
          <div className="faint" style={{ fontSize: "0.82rem" }}>{review.reviewer_name} · {formatDateTime(review.created_at)}</div>
        </div>
      )}
      {!review && !can.review && <p className="muted">Waiting for a doctor's review.</p>}

      {editing && (
        <form className="stack stack--sm" noValidate onSubmit={(e) => { e.preventDefault(); setError(""); save.mutate(); }}>
          <fieldset className="choice-group">
            <legend className="field__label">Your category</legend>
            {Object.entries(RISK_CATEGORIES).map(([value, c]) => (
              <label key={value} className={`choice choice--${c.tone} ${category === value ? "is-selected" : ""}`}
                htmlFor={`review-category-${value}`}>
                <input type="radio" name="review-category" id={`review-category-${value}`} value={value}
                  checked={category === value} onChange={() => setCategory(value)} />
                <Icon name={c.icon} size={16} />
                <span>{c.label}</span>
                {value === aiCategory && <span className="choice__tag">AI suggestion</span>}
              </label>
            ))}
          </fieldset>
          <TextArea id="review-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000}
            label={needsReason ? "Reason (required)" : "Comment (optional)"}
            hint={!aiCategory ? "The model gave no category, so explain your assessment."
              : category !== aiCategory ? "You are overriding the AI category; explain why." : undefined} />
          <Alert kind="error" id="review-error">{error}</Alert>
          <div className="row">
            <Button type="submit" id="review-submit" loading={save.isPending}
              disabled={!category || (needsReason && reason.trim().length < 3)}>
              {category && category === aiCategory ? "Confirm AI result" : "Save my category"}
            </Button>
            {review && <Button variant="ghost" id="review-cancel" onClick={() => setEditing(false)}>Cancel</Button>}
          </div>
        </form>
      )}

      {review && !editing && (
        <div className="row" style={{ marginTop: 12 }}>
          {can.review && (
            <Button variant="ghost" size="sm" id="review-change" onClick={() => {
              setCategory(review.final_category);
              setEditing(true);
            }}>Change review</Button>
          )}
          {can.writeReports && (openDraft ? (
            <Link to={`${base}/reports/${openDraft.id}`} className="btn btn--primary btn--sm" id="review-open-draft">
              <Icon name="report" size={14} /> Open draft report
            </Link>
          ) : (
            <Button size="sm" id="review-create-report" loading={createReport.isPending} onClick={() => createReport.mutate()}>
              <Icon name="report" size={14} /> Create report
            </Button>
          ))}
        </div>
      )}
      {forThisResult.length > 0 && (
        <ul className="review-box__reports">
          {forThisResult.map((r) => (
            <li key={r.id}>
              <Link to={`${base}/reports/${r.id}`} id={`review-report-${r.id}`}>{r.report_number}</Link>{" "}
              <Badge kind={REPORT_STATUS[r.status]?.kind}>{REPORT_STATUS[r.status]?.label || r.status}</Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
