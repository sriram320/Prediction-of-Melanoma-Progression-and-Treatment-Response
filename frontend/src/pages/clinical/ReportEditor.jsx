import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post } from "../../api/client.js";
import Icon from "../../components/Icon.jsx";
import PageLoading from "../../components/PageLoading.jsx";
import { Alert, Badge, Button, ConfirmDialog, PageHeader, Select, TextArea, TextInput } from "../../components/ui.jsx";
import {
  PATIENT_CATEGORY, RECOMMENDATION_PRESETS, REPORT_STATUS, RISK_CATEGORIES, siteLabel,
} from "../../utils/clinical.js";
import { downloadPath, openPath } from "../../utils/files.js";
import { errorMessage, formatDateTime } from "../../utils/format.js";
import { useCan, usePortalBase } from "./portal.js";

const EDITABLE = ["draft", "pending_review"];
const toForm = (r) => ({
  final_category: r.final_category || "", patient_summary: r.patient_summary || "",
  recommendation: r.recommendation || "", doctor_notes: r.doctor_notes || "",
});

function ReadOnly({ r }) {
  const cat = r.final_category && RISK_CATEGORIES[r.final_category];
  return (
    <div className="stack">
      <div className="report-field">
        <div className="report-field__label">Category</div>
        {cat ? <div><strong>{cat.label}</strong> <span className="faint">· patient sees: “{PATIENT_CATEGORY[r.final_category].label}”</span></div> : "–"}
      </div>
      <div className="report-field">
        <div className="report-field__label">Summary for the patient</div>
        <p style={{ whiteSpace: "pre-wrap" }}>{r.patient_summary || "–"}</p>
      </div>
      <div className="report-field">
        <div className="report-field__label">Recommendation</div>
        <p>{r.recommendation || "–"}</p>
      </div>
      {r.doctor_notes != null && (
        <div className="report-field">
          <div className="report-field__label">Doctor's notes (clinician copy only)</div>
          <p style={{ whiteSpace: "pre-wrap" }}>{r.doctor_notes || "–"}</p>
        </div>
      )}
    </div>
  );
}

export default function ReportEditor() {
  const { reportId } = useParams();
  const base = usePortalBase();
  const can = useCan();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const key = ["report", reportId];
  const { data: r, isLoading, isError, error } = useQuery({ queryKey: key, queryFn: () => get(`/reports/${reportId}`) });
  const [form, setForm] = useState(null);
  const [notice, setNotice] = useState({ kind: "", text: "" });
  const [confirm, setConfirm] = useState(null); // "sign" | "release"

  useEffect(() => { if (r) setForm(toForm(r)); }, [r]);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const fail = (err) => setNotice({ kind: "error", text: errorMessage(err) });
  const after = (updated, text) => {
    queryClient.setQueryData(key, updated);
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    if (updated.lesion_id) queryClient.invalidateQueries({ queryKey: ["lesion", updated.lesion_id, "reports"] });
    setNotice({ kind: "success", text });
    setConfirm(null);
  };

  const body = () => {
    const out = { patient_summary: form.patient_summary.trim() || null, recommendation: form.recommendation.trim() || null,
      doctor_notes: form.doctor_notes.trim() || null };
    if (!r.category_from_review) out.final_category = form.final_category || null;
    return out;
  };
  const save = useMutation({ mutationFn: () => patch(`/reports/${reportId}`, body()), onSuccess: (u) => after(u, "Draft saved."), onError: fail });
  const sign = useMutation({
    mutationFn: async () => {
      await patch(`/reports/${reportId}`, body());
      return post(`/reports/${reportId}/sign`);
    },
    onSuccess: (u) => after(u, "Report signed. The PDFs are ready; release it to make it visible to the patient."),
    onError: (err) => { setConfirm(null); fail(err); },
  });
  const release = useMutation({
    mutationFn: () => post(`/reports/${reportId}/release`),
    onSuccess: (u) => after(u, "Released. The patient can now see this report in their portal."),
    onError: (err) => { setConfirm(null); fail(err); },
  });
  const amend = useMutation({
    mutationFn: () => post(`/reports/${reportId}/amend`),
    onSuccess: (u) => { queryClient.invalidateQueries({ queryKey: ["reports"] }); navigate(`${base}/reports/${u.id}`); },
    onError: fail,
  });
  const pdf = async (variant, download) => {
    setNotice({});
    const path = `/reports/${reportId}/pdf?variant=${variant}${download ? "&download=true" : ""}`;
    try {
      if (download) await downloadPath(path, `${r.report_number}-${variant}.pdf`);
      else await openPath(path);
    } catch (err) { fail(err); }
  };

  if (isLoading || (r && !form)) return <PageLoading />;
  if (isError) return <Alert kind="error">{errorMessage(error)}</Alert>;
  const editable = EDITABLE.includes(r.status) && can.writeReports;
  const status = REPORT_STATUS[r.status] || { label: r.status };

  return (
    <>
      {r.lesion_id && (
        <Link to={`${base}/lesions/${r.lesion_id}`} className="row faint" id="report-back-link" style={{ marginBottom: 16, gap: 6 }}>
          <Icon name="arrowLeft" size={16} /> {r.lesion_label}
        </Link>
      )}
      <PageHeader eyebrow={`Report ${r.report_number} · version ${r.version}`} title={r.patient_name}
        subtitle={`MRN ${r.mrn}${r.lesion_label ? ` · ${r.lesion_label} · ${siteLabel(r.anatomical_site)}` : ""}`}
        actions={<Badge kind={status.kind} dot>{status.label}</Badge>} />

      <div className="stack">
        {r.model?.is_mock && <Alert kind="warning">Based on the MOCK model. The PDFs carry a "not for clinical use" watermark.</Alert>}
        {r.supersedes_number && <Alert kind="info">This version replaces report {r.supersedes_number}. The patient keeps seeing the old version until this one is released.</Alert>}
        {r.superseded_by_id && (
          <Alert kind="warning">
            A newer version of this report exists. <Link to={`${base}/reports/${r.superseded_by_id}`} id="report-newer-link">Open it</Link>.
          </Alert>
        )}
        <Alert kind={notice.kind || "info"} id="report-notice">{notice.text}</Alert>

        <section className="card">
          {editable ? (
            <form className="stack" noValidate onSubmit={(e) => { e.preventDefault(); setNotice({}); save.mutate(); }}>
              {r.category_from_review ? (
                <div className="report-field">
                  <div className="report-field__label">Category</div>
                  {r.final_category ? (
                    <div><strong>{RISK_CATEGORIES[r.final_category].label}</strong> <span className="faint">· from your review of the AI result</span></div>
                  ) : (
                    <Alert kind="warning">
                      Review the AI result first; its category is used here.{" "}
                      <Link to={`${base}/lesions/${r.lesion_id}`} id="report-review-link">Go to the lesion</Link>
                    </Alert>
                  )}
                </div>
              ) : (
                <Select id="report-category" label="Category" value={form.final_category} onChange={set("final_category")}
                  options={[{ value: "", label: "Choose a category" },
                    ...Object.entries(RISK_CATEGORIES).map(([value, c]) => ({ value, label: c.label }))]} />
              )}
              <TextArea id="report-summary" label="Summary for the patient" rows={5} value={form.patient_summary}
                onChange={set("patient_summary")} maxLength={4000}
                hint="Shown to the patient. Use plain language; no AI scores or technical terms." />
              <div className="stack stack--sm">
                <TextInput id="report-recommendation" label="Recommendation" value={form.recommendation}
                  onChange={set("recommendation")} maxLength={500} />
                <div className="row" style={{ gap: 6 }}>
                  {RECOMMENDATION_PRESETS.map((p, i) => (
                    <button key={p} type="button" className="chip" id={`report-preset-${i}`}
                      onClick={() => setForm((f) => ({ ...f, recommendation: p }))}>{p}</button>
                  ))}
                </div>
              </div>
              <TextArea id="report-notes" label="Doctor's notes" rows={5} value={form.doctor_notes} onChange={set("doctor_notes")}
                maxLength={8000} hint="Printed only on the clinician copy." />
              <div className="row">
                <Button type="submit" variant="secondary" id="report-save" loading={save.isPending}>Save draft</Button>
                <Button id="report-sign" onClick={() => setConfirm("sign")}
                  disabled={!(r.category_from_review ? r.final_category : form.final_category) || !form.patient_summary.trim() || !form.recommendation.trim()}>
                  <Icon name="check" size={16} /> Sign report
                </Button>
              </div>
            </form>
          ) : <ReadOnly r={r} />}
        </section>

        {r.has_pdf && (
          <section className="card">
            <div className="row row--between">
              <div>
                <h2 className="card__title">Signed by {r.signed_by_name}</h2>
                <div className="faint" style={{ fontSize: "0.85rem" }}>
                  {formatDateTime(r.signed_at)}{r.released_at ? ` · released ${formatDateTime(r.released_at)}` : " · not yet visible to the patient"}
                </div>
              </div>
              <div className="row" style={{ gap: 6 }}>
                <Button variant="secondary" size="sm" id="report-open-patient" onClick={() => pdf("patient", false)}>
                  <Icon name="eye" size={14} /> Patient copy
                </Button>
                {can.viewAiResults && (
                  <Button variant="secondary" size="sm" id="report-open-clinician" onClick={() => pdf("clinician", false)}>
                    <Icon name="eye" size={14} /> Clinician copy
                  </Button>
                )}
                <Button variant="ghost" size="sm" id="report-download" onClick={() => pdf("patient", true)}>Download</Button>
              </div>
            </div>
            <div className="row" style={{ marginTop: 14 }}>
              {r.status === "signed" && can.releaseReports && (
                <Button id="report-release" onClick={() => setConfirm("release")}>Release to patient</Button>
              )}
              {["signed", "released"].includes(r.status) && can.writeReports && !r.superseded_by_id && (
                <Button variant="secondary" id="report-amend" loading={amend.isPending} onClick={() => amend.mutate()}>
                  Amend (new version)
                </Button>
              )}
            </div>
          </section>
        )}
      </div>

      {confirm === "sign" && (
        <ConfirmDialog id="report-sign-dialog" title="Sign this report?" confirmLabel="Sign report" loading={sign.isPending}
          onCancel={() => setConfirm(null)} onConfirm={() => sign.mutate()}>
          Signing saves your changes, creates the patient and clinician PDFs with your name and registration number,
          and locks the report. Later changes need an amendment.
        </ConfirmDialog>
      )}
      {confirm === "release" && (
        <ConfirmDialog id="report-release-dialog" title="Release to the patient?" confirmLabel="Release" loading={release.isPending}
          onCancel={() => setConfirm(null)} onConfirm={() => release.mutate()}>
          The patient will see this report and can download the patient copy from their portal.
          {r.supersedes_number && ` Report ${r.supersedes_number} will be replaced.`}
        </ConfirmDialog>
      )}
    </>
  );
}
