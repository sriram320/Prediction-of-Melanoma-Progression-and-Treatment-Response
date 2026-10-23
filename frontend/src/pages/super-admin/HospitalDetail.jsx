import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post } from "../../api/client.js";
import Icon from "../../components/Icon.jsx";
import {
  Alert, Badge, Button, ConfirmDialog, EmptyState, PageHeader, SecretDialog, StatCard, TextInput,
} from "../../components/ui.jsx";
import PageLoading from "../../components/PageLoading.jsx";
import { errorMessage, formatDate, formatDateTime } from "../../utils/format.js";
import StaffFormModal from "../shared/StaffFormModal.jsx";
import StaffStatus from "../shared/StaffStatus.jsx";

const toForm = (h) => ({
  name: h.name, address: h.address || "", contact_email: h.contact_email || "", contact_phone: h.contact_phone || "",
});

function DetailsForm({ hospital }) {
  const queryClient = useQueryClient();
  const initial = toForm(hospital);
  const [form, setForm] = useState(initial);
  const [msg, setMsg] = useState({ kind: "", text: "" });
  useEffect(() => setForm(toForm(hospital)), [hospital]);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const dirty = Object.keys(initial).some((k) => initial[k] !== form[k]);

  const save = useMutation({
    mutationFn: () => patch(`/admin/hospitals/${hospital.id}`, {
      name: form.name.trim(), address: form.address.trim() || null,
      contact_email: form.contact_email.trim() || null, contact_phone: form.contact_phone.trim() || null,
    }),
    onSuccess: (data) => {
      queryClient.setQueryData(["admin", "hospital", hospital.id], data);
      queryClient.invalidateQueries({ queryKey: ["admin", "hospitals"] });
      setMsg({ kind: "success", text: "Hospital details saved." });
    },
    onError: (err) => setMsg({ kind: "error", text: errorMessage(err) }),
  });

  return (
    <form className="stack" noValidate onSubmit={(e) => { e.preventDefault(); setMsg({}); save.mutate(); }}>
      <Alert kind={msg.kind || "info"} id="hospital-details-msg">{msg.text}</Alert>
      <div className="form-grid">
        <TextInput id="hospital-edit-name" label="Name" value={form.name} onChange={set("name")} required />
        <TextInput id="hospital-edit-code" label="Hospital code" value={hospital.code} disabled
          hint="The code cannot be changed; staff use it to sign in." />
        <div className="field--full">
          <TextInput id="hospital-edit-address" label="Address" value={form.address} onChange={set("address")} />
        </div>
        <TextInput id="hospital-edit-email" label="Contact email" type="email" value={form.contact_email}
          onChange={set("contact_email")} />
        <TextInput id="hospital-edit-phone" label="Contact phone" type="tel" value={form.contact_phone}
          onChange={set("contact_phone")} />
      </div>
      <div className="row">
        <Button type="submit" loading={save.isPending} disabled={!dirty || !form.name.trim()} id="hospital-edit-save">
          Save changes
        </Button>
        {dirty && <Button variant="ghost" id="hospital-edit-reset" onClick={() => setForm(initial)}>Discard</Button>}
      </div>
    </form>
  );
}

export default function HospitalDetail() {
  const { hospitalId } = useParams();
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [secret, setSecret] = useState(null);
  const [confirmToggle, setConfirmToggle] = useState(false);

  const { data: h, isLoading, isError, error } = useQuery({
    queryKey: ["admin", "hospital", hospitalId],
    queryFn: () => get(`/admin/hospitals/${hospitalId}`),
  });

  const toggle = useMutation({
    mutationFn: () => patch(`/admin/hospitals/${hospitalId}`, { is_active: !h.is_active }),
    onSuccess: (data) => {
      queryClient.setQueryData(["admin", "hospital", hospitalId], data);
      queryClient.invalidateQueries({ queryKey: ["admin", "hospitals"] });
      setConfirmToggle(false);
    },
  });

  if (isLoading) return <PageLoading />;
  if (isError) return <Alert kind="error">{errorMessage(error)}</Alert>;

  return (
    <>
      <Link to="/admin" className="row faint" id="hospital-back-link" style={{ marginBottom: 16, gap: 6 }}>
        <Icon name="arrowLeft" size={16} /> All hospitals
      </Link>
      <PageHeader eyebrow={`Hospital · ${h.code}`} title={h.name}
        subtitle={`Registered ${formatDate(h.created_at)}`}
        actions={<>
          {h.is_active ? <Badge kind="success" dot>Active</Badge> : <Badge kind="danger" dot>Inactive</Badge>}
          <Button variant={h.is_active ? "danger" : "primary"} id="hospital-toggle-active"
            onClick={() => setConfirmToggle(true)}>
            {h.is_active ? "Deactivate" : "Reactivate"}
          </Button>
        </>} />

      {!h.is_active && (
        <div style={{ marginBottom: 16 }}>
          <Alert kind="warning">This hospital is inactive. Its staff and patients cannot sign in.</Alert>
        </div>
      )}

      <div className="stat-grid" style={{ marginBottom: 24 }}>
        <StatCard label="Staff accounts" value={h.staff_count} />
        <StatCard label="Patients" value={h.patient_count} />
        <StatCard label="Hospital admins" value={h.admins.length} />
      </div>

      <div className="stack stack--lg">
        <section className="card" aria-labelledby="hospital-details-heading">
          <h2 id="hospital-details-heading" className="card__title" style={{ marginBottom: 16 }}>Details</h2>
          <DetailsForm hospital={h} />
        </section>

        <section className="card card--flush" aria-labelledby="hospital-admins-heading">
          <div className="card__header" style={{ padding: "20px 24px 0" }}>
            <div>
              <h2 id="hospital-admins-heading" className="card__title">Hospital administrators</h2>
              <p className="faint" style={{ fontSize: "0.85rem" }}>They manage this hospital's doctors and technicians.</p>
            </div>
            <Button id="hospital-add-admin" onClick={() => setAdding(true)}><Icon name="plus" /> Add admin</Button>
          </div>
          {h.admins.length === 0 ? (
            <EmptyState icon="users" title="No administrators yet">
              <p>Add the first hospital admin so the hospital can onboard its staff.</p>
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Name</th><th>Email</th><th>Status</th><th>Last sign in</th></tr></thead>
                <tbody>
                  {h.admins.map((a) => (
                    <tr key={a.id}>
                      <td className="table__primary">{a.full_name}</td>
                      <td>{a.email}</td>
                      <td><StaffStatus user={a} /></td>
                      <td className="faint">{formatDateTime(a.last_login_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {adding && (
        <StaffFormModal id="add-admin-modal" title={`Add an administrator to ${h.code}`} fixedRole="hospital_admin"
          onClose={() => setAdding(false)}
          onSubmit={async (payload) => {
            const res = await post(`/admin/hospitals/${hospitalId}/admins`, payload);
            queryClient.invalidateQueries({ queryKey: ["admin", "hospital", hospitalId] });
            setAdding(false);
            setSecret({ name: res.user.full_name, email: res.user.email, password: res.temp_password });
          }} />
      )}

      {secret && (
        <SecretDialog id="admin-temp-password" title="Administrator created" secret={secret.password}
          label={`Temporary password for ${secret.name} (${secret.email}). They sign in at the hospital login with code ${h.code}.`}
          onClose={() => setSecret(null)} />
      )}

      {confirmToggle && (
        <ConfirmDialog id="hospital-toggle-dialog" danger={h.is_active} loading={toggle.isPending}
          title={h.is_active ? `Deactivate ${h.name}?` : `Reactivate ${h.name}?`}
          confirmLabel={h.is_active ? "Deactivate hospital" : "Reactivate hospital"}
          onCancel={() => setConfirmToggle(false)} onConfirm={() => toggle.mutate()}>
          {h.is_active
            ? "All staff and patients of this hospital will be signed out at their next request and cannot sign in until it is reactivated. No data is deleted."
            : "Staff and patients of this hospital will be able to sign in again."}
          {toggle.isError && <div style={{ marginTop: 12 }}><Alert kind="error">{errorMessage(toggle.error)}</Alert></div>}
        </ConfirmDialog>
      )}
    </>
  );
}
