import { useAuth } from "../../auth/AuthContext.jsx";
import { ROLE_LABELS } from "../../auth/roles.js";
import { PageHeader } from "../../components/ui.jsx";
import ChangePasswordForm from "./ChangePasswordForm.jsx";

export default function AccountPage() {
  const { user } = useAuth();
  const rows = [
    ["Name", user.full_name],
    ["Role", ROLE_LABELS[user.role]],
    ["Email", user.email || "–"],
    ["Phone", user.phone || "–"],
    ...(user.hospital ? [["Hospital", `${user.hospital.name} (${user.hospital.code})`]] : []),
  ];
  return (
    <>
      <PageHeader eyebrow="Account" title="My account" subtitle="Your sign-in details and password." />
      <div className="form-grid" style={{ alignItems: "start" }}>
        <section className="card" aria-labelledby="account-details-heading">
          <h2 id="account-details-heading" className="card__title" style={{ marginBottom: 16 }}>Details</h2>
          <dl className="stack stack--sm" style={{ margin: 0 }}>
            {rows.map(([k, v]) => (
              <div key={k} className="row row--between" style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
                <dt className="faint">{k}</dt>
                <dd style={{ margin: 0, fontWeight: 500 }}>{v}</dd>
              </div>
            ))}
          </dl>
          <p className="faint" style={{ fontSize: "0.82rem", marginTop: 16 }}>
            To change your name, email or phone, contact your {user.role === "patient" ? "hospital" : "administrator"}.
          </p>
        </section>
        <section className="card" aria-labelledby="account-password-heading">
          <h2 id="account-password-heading" className="card__title" style={{ marginBottom: 16 }}>Change password</h2>
          <ChangePasswordForm idPrefix="account-password" />
        </section>
      </div>
    </>
  );
}
