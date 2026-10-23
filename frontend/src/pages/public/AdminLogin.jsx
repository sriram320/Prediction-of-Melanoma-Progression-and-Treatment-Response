import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { HOME_BY_ROLE } from "../../auth/roles.js";
import { Alert, Button, TextInput } from "../../components/ui.jsx";
import AuthLayout from "../../layouts/AuthLayout.jsx";
import { errorMessage } from "../../utils/format.js";
import { useLoginRedirect } from "./useLoginRedirect.js";

export default function AdminLogin() {
  const { user, loginAdmin } = useAuth();
  const redirect = useLoginRedirect();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={HOME_BY_ROLE[user.role]} replace />;

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      redirect(await loginAdmin(email.trim(), password));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <AuthLayout variant="admin">
      <h1>Platform admin</h1>
      <p className="muted" style={{ marginBottom: 24 }}>Restricted to MelanoTrack platform administrators.</p>
      <form className="stack" onSubmit={onSubmit} noValidate>
        <Alert kind="error" id="admin-login-error">{error}</Alert>
        <TextInput id="admin-login-email" label="Email" type="email" autoComplete="username"
          value={email} onChange={(e) => setEmail(e.target.value)} required />
        <TextInput id="admin-login-password" label="Password" type="password" autoComplete="current-password"
          value={password} onChange={(e) => setPassword(e.target.value)} required />
        <Button type="submit" block loading={busy} id="admin-login-submit" disabled={!email || !password}>
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
