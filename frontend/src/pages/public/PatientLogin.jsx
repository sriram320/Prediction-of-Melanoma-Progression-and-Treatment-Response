import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { HOME_BY_ROLE } from "../../auth/roles.js";
import { Alert, Button, TextInput } from "../../components/ui.jsx";
import AuthLayout from "../../layouts/AuthLayout.jsx";
import { errorMessage } from "../../utils/format.js";
import { useLoginRedirect } from "./useLoginRedirect.js";

export default function PatientLogin() {
  const { user, loginPatient } = useAuth();
  const redirect = useLoginRedirect();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={HOME_BY_ROLE[user.role]} replace />;

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      redirect(await loginPatient(identifier.trim(), password));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <AuthLayout variant="patient">
      <h1>Patient sign in</h1>
      <p className="muted" style={{ marginBottom: 24 }}>Use the email or phone number you registered with.</p>
      <form className="stack" onSubmit={onSubmit} noValidate>
        <Alert kind="error" id="patient-login-error">{error}</Alert>
        <TextInput id="patient-login-identifier" label="Email or phone number" autoComplete="username"
          value={identifier} onChange={(e) => setIdentifier(e.target.value)} required />
        <TextInput id="patient-login-password" label="Password" type="password" autoComplete="current-password"
          value={password} onChange={(e) => setPassword(e.target.value)} required />
        <Button type="submit" block loading={busy} id="patient-login-submit" disabled={!identifier || !password}>
          Sign in
        </Button>
      </form>
      <p className="auth__switch">
        First time here? <Link to="/patient/activate" id="patient-login-to-activate">Activate with your invite code</Link>
      </p>
      <p className="auth__switch" style={{ marginTop: 8 }}>
        Hospital staff? <Link to="/hospital/login" id="patient-login-to-hospital">Use the hospital sign in</Link>
      </p>
    </AuthLayout>
  );
}
