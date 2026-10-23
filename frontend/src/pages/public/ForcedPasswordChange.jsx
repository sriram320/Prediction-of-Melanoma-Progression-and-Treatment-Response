import { useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { HOME_BY_ROLE } from "../../auth/roles.js";
import { Alert, Button } from "../../components/ui.jsx";
import AuthLayout from "../../layouts/AuthLayout.jsx";
import ChangePasswordForm from "../shared/ChangePasswordForm.jsx";

/** Reached after signing in with a temporary password. The API blocks everything else until this is done. */
export default function ForcedPasswordChange() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const variant = user.role === "patient" ? "patient" : user.role === "super_admin" ? "admin" : "hospital";

  return (
    <AuthLayout variant={variant}>
      <h1>Set a new password</h1>
      <p className="muted" style={{ marginBottom: 20 }}>Signed in as {user.full_name}.</p>
      {user.must_change_password ? (
        <div className="stack">
          <Alert kind="info">You signed in with a temporary password. Choose your own password to continue.</Alert>
          <ChangePasswordForm idPrefix="forced-password"
            onDone={(me) => navigate(HOME_BY_ROLE[me.role] || "/", { replace: true })} />
        </div>
      ) : (
        <div className="stack">
          <Alert kind="success">Your password is up to date.</Alert>
          <Button id="forced-password-continue" onClick={() => navigate(HOME_BY_ROLE[user.role] || "/")}>Continue</Button>
        </div>
      )}
      <p className="auth__switch">
        <button type="button" className="btn btn--ghost btn--sm" id="forced-password-logout" onClick={() => logout()}>
          Sign out instead
        </button>
      </p>
    </AuthLayout>
  );
}
