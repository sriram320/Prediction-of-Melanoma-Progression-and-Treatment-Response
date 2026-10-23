import { useState } from "react";
import { Alert, Button, Modal, Select, TextInput } from "../../components/ui.jsx";
import { errorMessage } from "../../utils/format.js";

const ROLE_OPTIONS = [
  { value: "doctor", label: "Doctor" },
  { value: "technician", label: "Technician" },
  { value: "hospital_admin", label: "Hospital admin" },
];

/**
 * Create a staff account. `fixedRole` hides the role picker (super admin adding a hospital admin).
 * `onSubmit(payload)` must return a promise; errors are shown inline.
 */
export default function StaffFormModal({ id, title, fixedRole, onSubmit, onClose }) {
  const [form, setForm] = useState({ role: fixedRole || "doctor", full_name: "", email: "", phone: "", registration_no: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const payload = { full_name: form.full_name.trim(), email: form.email.trim(), phone: form.phone.trim() || null };
      if (!fixedRole) {
        payload.role = form.role;
        payload.registration_no = form.registration_no.trim() || null;
      }
      await onSubmit(payload);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Modal id={id} title={title} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose} id={`${id}-cancel`}>Cancel</Button>
        <Button type="submit" form={`${id}-form`} loading={busy} id={`${id}-submit`}
          disabled={!form.full_name.trim() || !form.email.trim()}>
          Create account
        </Button>
      </>}>
      <form id={`${id}-form`} className="stack" onSubmit={submit} noValidate>
        <Alert kind="error" id={`${id}-error`}>{error}</Alert>
        {!fixedRole && (
          <Select id={`${id}-role`} label="Role" value={form.role} onChange={set("role")} options={ROLE_OPTIONS} />
        )}
        <TextInput id={`${id}-name`} label="Full name" value={form.full_name} onChange={set("full_name")} required />
        <TextInput id={`${id}-email`} label="Work email" type="email" value={form.email} onChange={set("email")} required
          hint="Used to sign in together with the hospital code." />
        <TextInput id={`${id}-phone`} label="Phone (optional)" type="tel" value={form.phone} onChange={set("phone")} />
        {!fixedRole && form.role === "doctor" && (
          <TextInput id={`${id}-regno`} label="Medical registration no. (optional)" value={form.registration_no}
            onChange={set("registration_no")} />
        )}
        <p className="faint" style={{ fontSize: "0.82rem" }}>
          A temporary password is generated and shown once. The new user must change it at first sign in.
        </p>
      </form>
    </Modal>
  );
}
