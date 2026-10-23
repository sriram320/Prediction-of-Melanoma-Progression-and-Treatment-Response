import { useState } from "react";
import { post } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import { Alert, Button, TextInput } from "../../components/ui.jsx";
import { errorMessage } from "../../utils/format.js";
import { passwordProblem } from "./passwordRules.js";

export default function ChangePasswordForm({ idPrefix = "change-password", onDone }) {
  const { setUser } = useAuth();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const nextError = touched ? passwordProblem(form.next) : null;
  const confirmError = touched && form.confirm !== form.next ? "Passwords do not match" : null;

  async function onSubmit(e) {
    e.preventDefault();
    setTouched(true);
    setError("");
    setSuccess("");
    if (passwordProblem(form.next) || form.confirm !== form.next) return;
    setBusy(true);
    try {
      const me = await post("/auth/change-password", { current_password: form.current, new_password: form.next });
      setForm({ current: "", next: "", confirm: "" });
      setTouched(false);
      setSuccess("Your password has been changed.");
      setUser(me);
      onDone?.(me);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={onSubmit} noValidate>
      <Alert kind="error" id={`${idPrefix}-error`}>{error}</Alert>
      <Alert kind="success" id={`${idPrefix}-success`}>{success}</Alert>
      <TextInput id={`${idPrefix}-current`} label="Current password" type="password" autoComplete="current-password"
        value={form.current} onChange={set("current")} required />
      <TextInput id={`${idPrefix}-new`} label="New password" type="password" autoComplete="new-password"
        value={form.next} onChange={set("next")} error={nextError}
        hint="At least 10 characters, with letters and numbers." />
      <TextInput id={`${idPrefix}-confirm`} label="Confirm new password" type="password" autoComplete="new-password"
        value={form.confirm} onChange={set("confirm")} error={confirmError} />
      <div>
        <Button type="submit" loading={busy} id={`${idPrefix}-submit`} disabled={!form.current || !form.next}>
          Change password
        </Button>
      </div>
    </form>
  );
}
