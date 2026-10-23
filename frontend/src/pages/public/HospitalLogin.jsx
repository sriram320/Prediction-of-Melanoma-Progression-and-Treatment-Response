import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { HOME_BY_ROLE } from "../../auth/roles.js";
import { Alert, Button, TextInput } from "../../components/ui.jsx";
import AuthLayout from "../../layouts/AuthLayout.jsx";
import { errorMessage } from "../../utils/format.js";
import { useLoginRedirect } from "./useLoginRedirect.js";

export default function HospitalLogin() {
  const { user, loginHospital } = useAuth();
  const redirect = useLoginRedirect();
  const [form, setForm] = useState({ code: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={HOME_BY_ROLE[user.role]} replace />;

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      redirect(await loginHospital(form.code.trim(), form.email.trim(), form.password));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <AuthLayout variant="hospital">
      <h1>Hospital sign in</h1>
      <p className="muted" style={{ marginBottom: 24 }}>For doctors, technicians and hospital administrators.</p>
      <form className="stack" onSubmit={onSubmit} noValidate>
        <Alert kind="error" id="hospital-login-error">{error}</Alert>
        <TextInput id="hospital-login-code" label="Hospital code" className="input--upper" autoComplete="organization"
          placeholder="e.g. DEMO01" value={form.code} onChange={set("code")} required maxLength={16} />
        <TextInput id="hospital-login-email" label="Work email" type="email" autoComplete="username"
          value={form.email} onChange={set("email")} required />
        <TextInput id="hospital-login-password" label="Password" type="password" autoComplete="current-password"
          value={form.password} onChange={set("password")} required />
        <Button type="submit" block loading={busy} id="hospital-login-submit"
          disabled={!form.code || !form.email || !form.password}>
          Sign in
        </Button>
      </form>
      <p className="auth__switch">
        Are you a patient? <Link to="/patient/login" id="hospital-login-to-patient">Sign in here</Link>
      </p>
    </AuthLayout>
  );
}
