import { useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../../api/client.js";
import Icon from "../../components/Icon.jsx";
import PageLoading from "../../components/PageLoading.jsx";
import SecureImage from "../../components/SecureImage.jsx";
import {
  Alert, Badge, Button, EmptyState, Modal, PageHeader, SecretDialog, Select, TextInput,
} from "../../components/ui.jsx";
import { ANATOMICAL_SITES, fitzpatrickShort, MEDICAL_HISTORY, sexLabel, siteLabel } from "../../utils/clinical.js";
import { errorMessage, formatDate, formatDateTime } from "../../utils/format.js";
import DocumentsPanel from "./DocumentsPanel.jsx";
import PatientFormModal from "./PatientFormModal.jsx";
import { usePortalBase } from "./portal.js";

const TABS = [
  { id: "lesions", label: "Lesions & scans" },
  { id: "documents", label: "Documents" },
  { id: "profile", label: "Profile" },
];

function AddLesionModal({ patientId, onClose, onCreated }) {
  const [label, setLabel] = useState("");
  const [site, setSite] = useState("posterior_torso");
  const [error, setError] = useState("");
  const create = useMutation({
    mutationFn: () => post(`/patients/${patientId}/lesions`, { label: label.trim(), anatomical_site: site }),
    onSuccess: onCreated,
    onError: (err) => setError(errorMessage(err)),
  });
  return (
    <Modal id="add-lesion-modal" title="Add a lesion to track" onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose} id="add-lesion-cancel">Cancel</Button>
        <Button type="submit" form="add-lesion-form" loading={create.isPending} id="add-lesion-submit"
          disabled={!label.trim()}>Add lesion</Button>
      </>}>
      <form id="add-lesion-form" className="stack" noValidate onSubmit={(e) => { e.preventDefault(); setError(""); create.mutate(); }}>
        <Alert kind="error" id="add-lesion-error">{error}</Alert>
        <TextInput id="add-lesion-label" label="Label" value={label} onChange={(e) => setLabel(e.target.value)}
          placeholder="e.g. L2 - left calf" maxLength={50} hint="A short name the team will recognise at every visit." />
        <Select id="add-lesion-site" label="Body site" value={site} onChange={(e) => setSite(e.target.value)}
          options={ANATOMICAL_SITES} />
      </form>
    </Modal>
  );
}

function LesionsTab({ patientId, lesions, base }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  return (
    <div className="stack">
      <div className="row row--between">
        <p className="muted">Each lesion has its own timeline of visits. The model compares visits of the same lesion.</p>
        <Button id="lesions-add-btn" onClick={() => setAdding(true)}><Icon name="plus" /> Add lesion</Button>
      </div>
      {lesions.length === 0 ? (
        <div className="card"><EmptyState icon="lesion" title="No lesions recorded">
          <p>Add the lesion you are monitoring, then record its first visit and upload scans.</p>
        </EmptyState></div>
      ) : (
        <div className="lesion-grid">
          {lesions.map((l) => (
            <Link key={l.id} to={`${base}/lesions/${l.id}`} className="card lesion-card" id={`lesion-card-${l.id}`}>
              <div className="lesion-card__thumb">
                {l.latest_image_file_id
                  ? <SecureImage fileId={l.latest_image_file_id} alt={`Latest scan of ${l.label}`} />
                  : <Icon name="lesion" size={32} />}
              </div>
              <div className="lesion-card__body">
                <div className="row row--between">
                  <strong>{l.label}</strong>
                  {l.status !== "active" && <Badge>{l.status}</Badge>}
                </div>
                <div className="faint" style={{ fontSize: "0.85rem" }}>{siteLabel(l.anatomical_site)}</div>
                <div className="muted" style={{ fontSize: "0.85rem", marginTop: 8 }}>
                  {l.visit_count === 0 ? "No visits yet"
                    : `${l.visit_count} visit${l.visit_count > 1 ? "s" : ""} · ${formatDate(l.first_visit_date)}`
                      + (l.visit_count > 1 ? ` to ${formatDate(l.last_visit_date)}` : "")}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
      {adding && (
        <AddLesionModal patientId={patientId} onClose={() => setAdding(false)} onCreated={(lesion) => {
          queryClient.invalidateQueries({ queryKey: ["patient", patientId] });
          setAdding(false);
          navigate(`${base}/lesions/${lesion.id}`);
        }} />
      )}
    </div>
  );
}

function ProfileTab({ p }) {
  const history = MEDICAL_HISTORY.filter((h) => p.medical_history?.[h.key] !== undefined)
    .map((h) => `${h.label}: ${p.medical_history[h.key] ? "yes" : "no"}`);
  const rows = [
    ["Full name", p.full_name],
    ["Date of birth", `${formatDate(p.date_of_birth)} (age band ${p.age_band})`],
    ["Sex", sexLabel(p.sex)],
    ["Skin type", fitzpatrickShort(p.fitzpatrick_type)],
    ["Phone", p.phone || "–"],
    ["Email", p.email || "–"],
    ["Address", p.address || "–"],
    ["Medical history", history.length ? history.join(" · ") : "Not recorded"],
    ["History notes", p.medical_history?.notes || "–"],
    ["Consent", p.consent_status ? `Given ${formatDateTime(p.consent_at)}` : "Not recorded"],
    ["Pseudonym (used for AI and exports)", p.pseudonym_id],
    ["Registered", formatDateTime(p.created_at)],
  ];
  return (
    <div className="card">
      <dl className="dl-grid">
        {rows.map(([k, v]) => (<div key={k} className="dl-grid__row"><dt>{k}</dt><dd>{v}</dd></div>))}
      </dl>
    </div>
  );
}

export default function PatientDetail() {
  const { patientId } = useParams();
  const base = usePortalBase();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("lesions");
  const [editing, setEditing] = useState(false);
  const [invite, setInvite] = useState(null);

  const patientQ = useQuery({ queryKey: ["patient", patientId], queryFn: () => get(`/patients/${patientId}`) });
  const lesionsQ = useQuery({ queryKey: ["patient", patientId, "lesions"], queryFn: () => get(`/patients/${patientId}/lesions`) });
  const createInvite = useMutation({
    mutationFn: () => post(`/patients/${patientId}/invite`),
    onSuccess: (res) => {
      setInvite(res);
      queryClient.invalidateQueries({ queryKey: ["patient", patientId] });
    },
  });

  if (patientQ.isLoading) return <PageLoading />;
  if (patientQ.isError) return <Alert kind="error">{errorMessage(patientQ.error)}</Alert>;
  const p = patientQ.data;
  const lesions = lesionsQ.data || [];

  return (
    <>
      <Link to={`${base}/patients`} className="row faint" id="patient-back-link" style={{ marginBottom: 16, gap: 6 }}>
        <Icon name="arrowLeft" size={16} /> All patients
      </Link>
      <PageHeader eyebrow={`MRN ${p.mrn} · ${p.pseudonym_id}`} title={p.full_name}
        subtitle={`${p.age_band} · ${sexLabel(p.sex)} · ${fitzpatrickShort(p.fitzpatrick_type)}`}
        actions={<Button variant="secondary" id="patient-edit-btn" onClick={() => setEditing(true)}>Edit details</Button>} />

      {location.state?.justRegistered && !p.has_account && !p.pending_invite && (
        <div style={{ marginBottom: 16 }}>
          <Alert kind="success">Patient registered. Create an invite code so they can use the patient portal.</Alert>
        </div>
      )}

      <div className="card" style={{ marginBottom: 20, padding: "16px 20px" }}>
        <div className="row row--between">
          <div className="row">
            {p.consent_status ? <Badge kind="success" dot>Consent recorded</Badge> : <Badge kind="warning" dot>No consent recorded</Badge>}
            {p.has_account ? <Badge kind="success" dot>Patient portal active</Badge>
              : p.pending_invite ? <Badge kind="accent" dot>Invite valid until {formatDate(p.pending_invite.expires_at)}</Badge>
                : <Badge>No patient portal access</Badge>}
          </div>
          {!p.has_account && (
            <Button variant="secondary" size="sm" id="patient-invite-btn" loading={createInvite.isPending}
              onClick={() => createInvite.mutate()}>
              <Icon name="key" size={14} /> {p.pending_invite ? "Issue a new invite code" : "Create invite code"}
            </Button>
          )}
        </div>
        {createInvite.isError && <div style={{ marginTop: 12 }}><Alert kind="error">{errorMessage(createInvite.error)}</Alert></div>}
      </div>

      <div className="tabs" role="tablist" aria-label="Patient record">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" className="tabs__btn" aria-selected={tab === t.id}
            aria-controls={`patient-panel-${t.id}`} id={`patient-tab-${t.id}`} onClick={() => setTab(t.id)}>
            {t.label}
            {t.id === "lesions" && <span className="tabs__count">{p.lesion_count}</span>}
            {t.id === "documents" && <span className="tabs__count">{p.document_count}</span>}
          </button>
        ))}
      </div>
      <section role="tabpanel" id={`patient-panel-${tab}`} aria-labelledby={`patient-tab-${tab}`}>
        {tab === "lesions" && (lesionsQ.isLoading ? <PageLoading /> : lesionsQ.isError
          ? <Alert kind="error">{errorMessage(lesionsQ.error)}</Alert>
          : <LesionsTab patientId={p.id} lesions={lesions} base={base} />)}
        {tab === "documents" && <DocumentsPanel patientId={p.id} lesions={lesions} />}
        {tab === "profile" && <ProfileTab p={p} />}
      </section>

      {editing && (
        <PatientFormModal patient={p} onClose={() => setEditing(false)} onSaved={(saved) => {
          queryClient.setQueryData(["patient", patientId], saved);
          queryClient.invalidateQueries({ queryKey: ["patients"] });
          setEditing(false);
        }} />
      )}
      {invite && (
        <SecretDialog id="patient-invite-dialog" title="Patient invite code" secret={invite.invite_code}
          label={`Give this code to ${p.full_name}. They activate their account at ${window.location.origin}/patient/activate `
            + "with this code and their date of birth."}
          note={`Valid until ${formatDateTime(invite.expires_at)}. It is shown only once; issuing a new code cancels this one.`}
          onClose={() => setInvite(null)} />
      )}
    </>
  );
}
