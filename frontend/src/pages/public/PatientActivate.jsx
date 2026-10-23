import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { HOME_BY_ROLE } from "../../auth/roles.js";
import { Alert, Button, TextInput } from "../../components/ui.jsx";
import AuthLayout from "../../layouts/AuthLayout.jsx";
import { errorMessage } from "../../utils/format.js";
import { passwordProblem } from "../shared/passwordRules.js";

export default function PatientActivate() {
  const { user, activatePatient } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ code: "", dob: "", email: "", phone: "", password: "", confirm: "" });
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={HOME_BY_ROLE[user.role]} replace />;

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const pwError = touched ? passwordProblem(form.password) : null;
  const confirmError = touched && form.confirm && form.confirm !== form.password ? "Passwords do not match" : null;
  const contactError = touched && !form.email.trim() && !form.phone.trim()
    ? "Enter an email address or a phone number" : null;

  async function onSubmit(e) {
    e.preventDefault();
    setTouched(true);
    setError("");
    if (passwordProblem(form.password) || form.confirm !== form.password || (!form.email.trim() && !form.phone.trim())) return;
    setBusy(true);
    try {
      await activatePatient({
        invite_code: form.code.trim(),
        date_of_birth: form.dob,
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        password: form.password,
      });
      navigate("/patient", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <AuthLayout variant="patient">
      <h1>Activate your account</h1>
      <p className="muted" style={{ marginBottom: 24 }}>
        Enter the invite code your hospital gave you and your date of birth, then choose how you will sign in.
      </p>
      <form className="stack" onSubmit={onSubmit} noValidate>
        <Alert kind="error" id="activate-error">{error}</Alert>
        <TextInput id="activate-code" label="Invite code" className="input--upper" placeholder="XXXX-XXXX-XXXX"
          value={form.code} onChange={set("code")} required autoComplete="one-time-code" />
        <TextInput id="activate-dob" label="Date of birth" type="date" value={form.dob} onChange={set("dob")} required
          max={new Date().toISOString().slice(0, 10)} />
        <TextInput id="activate-email" label="Email (optional if you add a phone)" type="email" autoComplete="email"
          value={form.email} onChange={set("email")} error={contactError} />
        <TextInput id="activate-phone" label="Phone (optional if you add an email)" type="tel" autoComplete="tel"
          placeholder="+91 98xxx xxxxx" value={form.phone} onChange={set("phone")} />
        <TextInput id="activate-password" label="Choose a password" type="password" autoComplete="new-password"
          value={form.password} onChange={set("password")} error={pwError}
          hint="At least 10 characters, with letters and numbers." />
        <TextInput id="activate-confirm" label="Confirm password" type="password" autoComplete="new-password"
          value={form.confirm} onChange={set("confirm")} error={confirmError} />
        <Button type="submit" block loading={busy} id="activate-submit" disabled={!form.code || !form.dob}>
          Activate account
        </Button>
      </form>
      <p className="auth__switch">
        Already activated? <Link to="/patient/login" id="activate-to-login">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
