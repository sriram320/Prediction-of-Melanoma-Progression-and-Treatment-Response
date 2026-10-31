import { useState } from "react";
import { patch, post } from "../../api/client.js";
import { Alert, Button, Modal, Select, TextArea, TextInput } from "../../components/ui.jsx";
import { FITZPATRICK, MEDICAL_HISTORY, SEX_OPTIONS } from "../../utils/clinical.js";
import { errorMessage, fieldErrors, todayISO } from "../../utils/format.js";

const TRI = [{ value: "", label: "Not asked" }, { value: "yes", label: "Yes" }, { value: "no", label: "No" }];
const toTri = (v) => (v === true ? "yes" : v === false ? "no" : "");
const fromTri = (v) => (v === "yes" ? true : v === "no" ? false : null);

function initialForm(patient) {
  const history = patient?.medical_history || {};
  return {
    mrn: patient?.mrn || "",
    full_name: patient?.full_name || "",
    date_of_birth: patient?.date_of_birth || "",
    sex: patient?.sex || "unknown",
    fitzpatrick_type: patient?.fitzpatrick_type ? String(patient.fitzpatrick_type) : "",
    phone: patient?.phone || "",
    email: patient?.email || "",
    address: patient?.address || "",
    consent_status: patient?.consent_status ?? false,
    notes: history.notes || "",
    ...Object.fromEntries(MEDICAL_HISTORY.map((h) => [h.key, toTri(history[h.key])])),
  };
}

/** Register a patient (no `patient`) or edit one. Calls onSaved(patientOut). */
export default function PatientFormModal({ patient, onClose, onSaved }) {
  const editing = Boolean(patient);
  const [form, setForm] = useState(() => initialForm(patient));
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const idp = editing ? "edit-patient" : "new-patient";

  async function submit(e) {
    e.preventDefault();
    setError("");
    setErrors({});
    setBusy(true);
    const medical_history = { notes: form.notes.trim() || null };
    MEDICAL_HISTORY.forEach((h) => { medical_history[h.key] = fromTri(form[h.key]); });
    const body = {
      mrn: form.mrn.trim(), full_name: form.full_name.trim(), date_of_birth: form.date_of_birth, sex: form.sex,
      fitzpatrick_type: form.fitzpatrick_type ? Number(form.fitzpatrick_type) : null,
      phone: form.phone.trim() || null, email: form.email.trim() || null, address: form.address.trim() || null,
      consent_status: form.consent_status, medical_history,
    };
    try {
      const saved = editing ? await patch(`/patients/${patient.id}`, body) : await post("/patients", body);
      onSaved(saved);
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Modal id={`${idp}-modal`} title={editing ? "Edit patient details" : "Register a patient"} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose} id={`${idp}-cancel`}>Cancel</Button>
        <Button type="submit" form={`${idp}-form`} loading={busy} id={`${idp}-submit`}
          disabled={!form.mrn.trim() || !form.full_name.trim() || !form.date_of_birth}>
          {editing ? "Save changes" : "Register patient"}
        </Button>
      </>}>
      <form id={`${idp}-form`} className="stack" onSubmit={submit} noValidate>
        <Alert kind="error" id={`${idp}-error`}>{error}</Alert>
        <div className="form-grid">
          <TextInput id={`${idp}-mrn`} label="Medical record number (MRN)" value={form.mrn} onChange={set("mrn")}
            error={errors.mrn} required maxLength={50} />
          <TextInput id={`${idp}-name`} label="Full name" value={form.full_name} onChange={set("full_name")}
            error={errors.full_name} required autoComplete="off" />
          <TextInput id={`${idp}-dob`} label="Date of birth" type="date" value={form.date_of_birth}
            onChange={set("date_of_birth")} error={errors.date_of_birth} max={todayISO()} required />
          <Select id={`${idp}-sex`} label="Sex" value={form.sex} onChange={set("sex")} options={SEX_OPTIONS} />
          <div className="field--full">
            <Select id={`${idp}-fitz`} label="Fitzpatrick skin type" value={form.fitzpatrick_type}
              onChange={set("fitzpatrick_type")} hint="Used to check the model performs equally across skin types."
              options={[{ value: "", label: "Not recorded" }, ...FITZPATRICK.map((f) => ({ ...f, value: String(f.value) }))]} />
          </div>
          <TextInput id={`${idp}-phone`} label="Phone" type="tel" value={form.phone} onChange={set("phone")}
            error={errors.phone} />
          <TextInput id={`${idp}-email`} label="Email" type="email" value={form.email} onChange={set("email")}
            error={errors.email} />
          <div className="field--full">
            <TextArea id={`${idp}-address`} label="Address" rows={2} value={form.address} onChange={set("address")} />
          </div>
        </div>

        <fieldset className="fieldset">
          <legend>Medical history</legend>
          <div className="form-grid">
            {MEDICAL_HISTORY.map((h) => (
              <Select key={h.key} id={`${idp}-${h.key}`} label={h.label} value={form[h.key]} onChange={set(h.key)}
                options={TRI} />
            ))}
            <div className="field--full">
              <TextArea id={`${idp}-history-notes`} label="Notes" rows={2} value={form.notes} onChange={set("notes")}
                maxLength={2000} />
            </div>
          </div>
        </fieldset>

        <label className="checkbox" htmlFor={`${idp}-consent`}>
          <input type="checkbox" id={`${idp}-consent`} checked={form.consent_status} onChange={set("consent_status")} />
          The patient has given informed consent for their images and records to be stored and analysed.
        </label>
        {!form.consent_status && (
          <Alert kind="warning">Without recorded consent, do not upload images for AI analysis.</Alert>
        )}
        {editing && patient.has_account && (
          <p className="faint" style={{ fontSize: "0.82rem" }}>
            Changing the email or phone here does not change how the patient signs in to the portal.
          </p>
        )}
      </form>
    </Modal>
  );
}
