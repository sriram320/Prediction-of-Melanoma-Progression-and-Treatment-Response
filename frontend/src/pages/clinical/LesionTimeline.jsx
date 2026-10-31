import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post, postForm } from "../../api/client.js";
import FileDrop from "../../components/FileDrop.jsx";
import Icon from "../../components/Icon.jsx";
import ImageViewer from "../../components/ImageViewer.jsx";
import PageLoading from "../../components/PageLoading.jsx";
import SecureImage from "../../components/SecureImage.jsx";
import {
  Alert, Badge, Button, Modal, PageHeader, Select, TextArea, TextInput,
} from "../../components/ui.jsx";
import { modalityLabel, MODALITIES, QUALITY_FLAGS, siteLabel } from "../../utils/clinical.js";
import { errorMessage, formatDate, formatDateTime, todayISO } from "../../utils/format.js";
import AnalysisPanel from "./AnalysisPanel.jsx";
import { useCan, usePortalBase } from "./portal.js";

const DEVICES = ["DermLite DL4", "DermLite DL5", "Heine Delta 30", "FotoFinder Medicam 1000", "Canfield VEOS HD2",
  "Smartphone + dermoscope attachment"];

function QualityBadge({ score, flags }) {
  if (score == null) return null;
  const kind = flags?.length ? "warning" : "success";
  return <Badge kind={kind} dot>Quality {Math.round(score * 100)}%</Badge>;
}

function AddVisitModal({ lesionId, onClose, onCreated }) {
  const [form, setForm] = useState({ visit_date: todayISO(), device_model: "", polarised: "", illumination: "", notes: "" });
  const [error, setError] = useState("");
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const create = useMutation({
    mutationFn: () => post(`/lesions/${lesionId}/visits`, {
      visit_date: form.visit_date, device_model: form.device_model.trim() || null,
      polarised: form.polarised === "" ? null : form.polarised === "yes",
      illumination: form.illumination.trim() || null, notes: form.notes.trim() || null,
    }),
    onSuccess: onCreated,
    onError: (err) => setError(errorMessage(err)),
  });
  return (
    <Modal id="add-visit-modal" title="Record a visit" onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose} id="add-visit-cancel">Cancel</Button>
        <Button type="submit" form="add-visit-form" loading={create.isPending} id="add-visit-submit"
          disabled={!form.visit_date}>Add visit</Button>
      </>}>
      <form id="add-visit-form" className="stack" noValidate onSubmit={(e) => { e.preventDefault(); setError(""); create.mutate(); }}>
        <Alert kind="error" id="add-visit-error">{error}</Alert>
        <div className="form-grid">
          <TextInput id="add-visit-date" label="Visit date" type="date" value={form.visit_date} onChange={set("visit_date")}
            max={todayISO()} required />
          <Select id="add-visit-polarised" label="Dermoscope light" value={form.polarised} onChange={set("polarised")}
            options={[{ value: "", label: "Not recorded" }, { value: "yes", label: "Polarised" }, { value: "no", label: "Non-polarised" }]} />
          <div className="field--full">
            <TextInput id="add-visit-device" label="Device model" value={form.device_model} onChange={set("device_model")}
              list="device-models" maxLength={100} hint="Recorded so results can be checked per device." />
            <datalist id="device-models">{DEVICES.map((d) => <option key={d} value={d} />)}</datalist>
          </div>
          <div className="field--full">
            <TextInput id="add-visit-illumination" label="Illumination (optional)" value={form.illumination}
              onChange={set("illumination")} maxLength={30} placeholder="e.g. white LED" />
          </div>
          <div className="field--full">
            <TextArea id="add-visit-notes" label="Notes (optional)" rows={2} value={form.notes} onChange={set("notes")} maxLength={2000} />
          </div>
        </div>
      </form>
    </Modal>
  );
}

function UploadPanel({ visit, onUploaded }) {
  const [files, setFiles] = useState([]);
  const [modality, setModality] = useState("dermoscopic");
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");
  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      fd.append("modality", modality);
      return postForm(`/visits/${visit.id}/images`, fd);
    },
    onSuccess: (res) => {
      setResults(res);
      setFiles([]);
      onUploaded();
    },
    onError: (err) => setError(errorMessage(err)),
  });
  const idp = `visit-${visit.id}-upload`;

  return (
    <div className="upload-panel stack stack--sm">
      <FileDrop id={`${idp}-drop`} files={files} onChange={(f) => { setFiles(f); setResults(null); }} multiple
        accept=".jpg,.jpeg,.png,.tif,.tiff,.dcm" hint="JPEG, PNG, TIFF or DICOM, up to 10 files of 50 MB each" />
      <div className="row">
        <div style={{ width: 220 }}>
          <label htmlFor={`${idp}-modality`} className="visually-hidden">Image type</label>
          <select id={`${idp}-modality`} className="select" value={modality} onChange={(e) => setModality(e.target.value)}>
            {MODALITIES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </div>
        <Button id={`${idp}-submit`} disabled={!files.length} loading={upload.isPending}
          onClick={() => { setError(""); upload.mutate(); }}>
          <Icon name="upload" size={16} /> Upload {files.length || ""} {files.length === 1 ? "file" : "files"}
        </Button>
      </div>
      <Alert kind="error" id={`${idp}-error`}>{error}</Alert>
      {results && (
        <ul className="upload-results" aria-label="Upload results">
          {results.map((r, i) => (
            <li key={`${r.filename}-${i}`}>
              <Alert kind={r.error ? (r.duplicate ? "warning" : "error") : r.quality_flags.length ? "warning" : "success"}>
                <strong>{r.filename}</strong>:{" "}
                {r.error || (r.quality_flags.length
                  ? `uploaded, but check the photo: ${r.quality_flags.map((f) => QUALITY_FLAGS[f] || f).join(", ")}. Retake it if you can.`
                  : "uploaded, quality looks good.")}
              </Alert>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ExcludeDialog({ visit, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const excluding = !visit.excluded;
  const save = useMutation({
    mutationFn: () => patch(`/visits/${visit.id}`, { excluded: excluding, reason: reason.trim() }),
    onSuccess: onDone,
    onError: (err) => setError(errorMessage(err)),
  });
  return (
    <Modal id="exclude-visit-modal" title={excluding ? `Exclude the visit of ${formatDate(visit.visit_date)}?`
      : `Include the visit of ${formatDate(visit.visit_date)} again?`} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose} id="exclude-visit-cancel">Cancel</Button>
        <Button variant={excluding ? "danger" : "primary"} loading={save.isPending} id="exclude-visit-confirm"
          disabled={reason.trim().length < 3} onClick={() => { setError(""); save.mutate(); }}>
          {excluding ? "Exclude visit" : "Include visit"}
        </Button>
      </>}>
      <div className="stack">
        <p className="muted">
          {excluding ? "Excluded visits stay in the record but are left out of AI analysis and hidden from the patient."
            : "The visit will be used in analysis again and shown to the patient."}
        </p>
        <Alert kind="error" id="exclude-visit-error">{error}</Alert>
        <TextArea id="exclude-visit-reason" label="Reason (kept in the audit log)" rows={3} value={reason}
          onChange={(e) => setReason(e.target.value)} maxLength={500} />
      </div>
    </Modal>
  );
}

function VisitCard({ visit, number, onOpen, onChanged }) {
  const can = useCan();
  const [showUpload, setShowUpload] = useState(visit.images.length === 0 && !visit.excluded);
  const [excluding, setExcluding] = useState(false);
  const meta = [visit.device_model, visit.polarised == null ? null : visit.polarised ? "Polarised" : "Non-polarised",
    visit.illumination].filter(Boolean).join(" · ");

  return (
    <li className={`visit ${visit.excluded ? "visit--excluded" : ""}`}>
      <span className="visit__dot" aria-hidden="true" />
      <article className="card visit__card" aria-labelledby={`visit-${visit.id}-title`}>
        <header className="row row--between">
          <div>
            <div className="faint visit__number">Visit {number}</div>
            <h2 id={`visit-${visit.id}-title`} className="visit__date">{formatDate(visit.visit_date)}</h2>
            {meta && <div className="faint" style={{ fontSize: "0.85rem" }}>{meta}</div>}
          </div>
          <div className="row">
            {visit.excluded && <Badge kind="danger" dot>Excluded from analysis</Badge>}
            <QualityBadge score={visit.quality_score} flags={visit.quality_flags} />
            {can.excludeVisits && (
              <Button variant="ghost" size="sm" id={`visit-${visit.id}-exclude`} onClick={() => setExcluding(true)}>
                {visit.excluded ? "Include again" : "Exclude"}
              </Button>
            )}
          </div>
        </header>
        {visit.notes && <p className="muted visit__notes">{visit.notes}</p>}

        {visit.images.length > 0 ? (
          <div className="thumb-grid">
            {visit.images.map((img) => (
              <button key={img.id} type="button" className="thumb" id={`image-${img.id}`}
                onClick={() => onOpen(img)} aria-label={`Open ${modalityLabel(img.modality)} image from ${formatDate(visit.visit_date)}`}>
                <SecureImage fileId={img.file_id} alt="" />
                <span className="thumb__meta">
                  <span>{modalityLabel(img.modality)}</span>
                  {img.quality_flags.map((f) => <span key={f} className="thumb__flag">{QUALITY_FLAGS[f] || f}</span>)}
                </span>
              </button>
            ))}
          </div>
        ) : (
          <p className="faint">No images uploaded for this visit yet.</p>
        )}

        <div style={{ marginTop: 12 }}>
          {showUpload ? <UploadPanel visit={visit} onUploaded={onChanged} /> : (
            <Button variant="secondary" size="sm" id={`visit-${visit.id}-add-images`} onClick={() => setShowUpload(true)}>
              <Icon name="plus" size={14} /> Add images
            </Button>
          )}
        </div>
      </article>
      {excluding && <ExcludeDialog visit={visit} onClose={() => setExcluding(false)}
        onDone={() => { setExcluding(false); onChanged(); }} />}
    </li>
  );
}

const ACTIVE = ["queued", "running"];

/** Run-analysis control plus the status of the latest job. Technicians see progress, never results. */
function AnalysisControl({ lesionId, job, analysable, onQueued }) {
  const can = useCan();
  const [error, setError] = useState("");
  const run = useMutation({
    mutationFn: () => post(`/lesions/${lesionId}/analyze`),
    onSuccess: onQueued,
    onError: (err) => setError(errorMessage(err)),
  });
  const active = job && ACTIVE.includes(job.status);
  return (
    <div className="stack stack--sm" style={{ marginBottom: 20 }}>
      <div className="card analysis-control">
        <div className="row row--between">
          <div className="row" style={{ gap: 10 }}>
            {active ? <span className="btn__spinner" aria-hidden="true" /> : <Icon name="activity" />}
            <div>
              <strong>{active ? (job.status === "queued" ? "Analysis queued" : "Analysis running")
                : job?.status === "succeeded" ? "Last analysis complete" : job?.status === "failed" ? "Last analysis failed"
                  : "Not analysed yet"}</strong>
              <div className="faint" style={{ fontSize: "0.82rem" }}>
                {active ? "This usually takes a few seconds. The page updates by itself."
                  : job ? `Requested ${formatDateTime(job.created_at)}`
                    : analysable === 0 ? "Upload scans first." : "Compares every non-excluded visit up to the latest one."}
                {!active && job?.status === "succeeded" && !can.viewAiResults && " · Waiting for doctor review."}
              </div>
            </div>
          </div>
          {can.runAnalysis && (
            <Button id="lesion-analyze-btn" loading={run.isPending} disabled={active || analysable === 0}
              onClick={() => { setError(""); run.mutate(); }}>
              <Icon name="play" size={14} /> {job ? "Run analysis again" : "Run analysis"}
            </Button>
          )}
        </div>
      </div>
      <Alert kind="error" id="lesion-analyze-error">{error}</Alert>
      {job?.status === "failed" && !active && (
        <Alert kind="error">The last analysis could not be completed. Run it again, or ask an administrator to check the AI service.</Alert>
      )}
    </div>
  );
}

function bestImage(visit) {
  return visit.images.find((i) => i.modality === "dermoscopic") || visit.images[0];
}

function CompareModal({ visits, onClose }) {
  const usable = visits.filter((v) => v.images.length);
  const [a, setA] = useState(usable[0]?.id);
  const [b, setB] = useState(usable[usable.length - 1]?.id);
  const pick = (id) => usable.find((v) => v.id === id);
  const items = [pick(a), pick(b)].filter(Boolean).map((v) => ({
    fileId: bestImage(v).file_id, caption: `${formatDate(v.visit_date)} · ${modalityLabel(bestImage(v).modality)}`,
  }));
  const options = usable.map((v) => ({
    value: v.id, label: `Visit ${visits.indexOf(v) + 1} · ${formatDate(v.visit_date)}${v.excluded ? " (excluded)" : ""}`,
  }));
  return (
    <ImageViewer id="compare-viewer" title="Compare visits" items={items} onClose={onClose}
      controls={(
        <div className="compare-picker" role="group" aria-label="Choose visits to compare">
          <Select id="compare-visit-a" label="Left" value={a} onChange={(e) => setA(e.target.value)} options={options} />
          <Select id="compare-visit-b" label="Right" value={b} onChange={(e) => setB(e.target.value)} options={options} />
        </div>
      )} />
  );
}

export default function LesionTimeline() {
  const { lesionId } = useParams();
  const base = usePortalBase();
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [viewing, setViewing] = useState(null);
  const [comparing, setComparing] = useState(false);
  const key = ["lesion", lesionId, "timeline"];
  const { data, isLoading, isError, error } = useQuery({
    queryKey: key,
    queryFn: () => get(`/lesions/${lesionId}/timeline`),
    refetchInterval: (query) => (ACTIVE.includes(query.state.data?.latest_job?.status) ? 2000 : false),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: key });
    if (data) queryClient.invalidateQueries({ queryKey: ["patient", data.patient.id] });
  };
  const withImages = useMemo(() => (data?.visits || []).filter((v) => v.images.length), [data]);

  if (isLoading) return <PageLoading />;
  if (isError) return <Alert kind="error">{errorMessage(error)}</Alert>;
  const { lesion, patient, visits, analysable_visit_count: analysable } = data;

  return (
    <>
      <Link to={`${base}/patients/${patient.id}`} className="row faint" id="lesion-back-link" style={{ marginBottom: 16, gap: 6 }}>
        <Icon name="arrowLeft" size={16} /> {patient.full_name}
      </Link>
      <PageHeader eyebrow={`Lesion · ${siteLabel(lesion.anatomical_site)}`} title={lesion.label}
        subtitle={`${patient.full_name} · MRN ${patient.mrn} · ${patient.pseudonym_id}`}
        actions={<>
          <Button variant="secondary" id="lesion-compare-btn" disabled={withImages.length < 2} onClick={() => setComparing(true)}
            title={withImages.length < 2 ? "Needs images from at least two visits" : undefined}>
            <Icon name="eye" size={16} /> Compare visits
          </Button>
          <Button id="lesion-add-visit-btn" onClick={() => setAdding(true)}><Icon name="plus" /> Record visit</Button>
        </>} />

      <AnalysisControl lesionId={lesion.id} job={data.latest_job} analysable={analysable} onQueued={refresh} />
      {data.latest_prediction && <div style={{ marginBottom: 20 }}><AnalysisPanel prediction={data.latest_prediction} /></div>}

      {analysable < 2 && (
        <div style={{ marginBottom: 20 }}>
          <Alert kind="info">
            {analysable === 0 ? "No scans yet. " : "Baseline only: one visit has scans. "}
            The model measures change between visits, so it needs scans from at least two visits of this lesion
            before it can estimate progression risk.
          </Alert>
        </div>
      )}

      {visits.length === 0 ? (
        <div className="card"><p className="muted">Record the first visit to start this lesion's timeline.</p></div>
      ) : (
        <ol className="timeline" aria-label="Visits, oldest first">
          {visits.map((v, i) => (
            <VisitCard key={v.id} visit={v} number={i + 1} onChanged={refresh}
              onOpen={(img) => setViewing({ fileId: img.file_id, caption: `${formatDate(v.visit_date)} · ${modalityLabel(img.modality)}` })} />
          ))}
        </ol>
      )}

      {adding && <AddVisitModal lesionId={lesion.id} onClose={() => setAdding(false)}
        onCreated={() => { setAdding(false); refresh(); }} />}
      {viewing && <ImageViewer id="image-viewer" title={lesion.label} items={[viewing]} onClose={() => setViewing(null)} />}
      {comparing && <CompareModal visits={visits} onClose={() => setComparing(false)} />}
    </>
  );
}
