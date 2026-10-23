import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post, qs } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import { ROLE_LABELS } from "../../auth/roles.js";
import Icon from "../../components/Icon.jsx";
import {
  Alert, Button, ConfirmDialog, EmptyState, PageHeader, Pagination, SecretDialog, Spinner,
} from "../../components/ui.jsx";
import { errorMessage, formatDateTime } from "../../utils/format.js";
import StaffFormModal from "../shared/StaffFormModal.jsx";
import StaffStatus from "../shared/StaffStatus.jsx";

const PAGE_SIZE = 20;
const FILTERS = [
  { value: "", label: "All" },
  { value: "doctor", label: "Doctors" },
  { value: "technician", label: "Technicians" },
  { value: "hospital_admin", label: "Admins" },
];

export default function Staff() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [role, setRole] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState(null);
  const [pending, setPending] = useState(null); // {kind: 'reset'|'toggle', member}

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["hospital", "staff", role, q, page],
    queryFn: () => get(`/hospital/staff${qs({ role, q, page, page_size: PAGE_SIZE })}`),
    placeholderData: keepPreviousData,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["hospital", "staff"] });
    queryClient.invalidateQueries({ queryKey: ["hospital", "stats"] });
  };

  const action = useMutation({
    mutationFn: ({ kind, member }) => patch(`/hospital/staff/${member.id}`,
      kind === "reset" ? { reset_password: true } : { is_active: !member.is_active }),
    onSuccess: (res, { kind }) => {
      refresh();
      setPending(null);
      if (kind === "reset") {
        setSecret({ title: "Password reset", name: res.user.full_name, email: res.user.email, password: res.temp_password });
      }
    },
  });

  return (
    <>
      <PageHeader eyebrow={user.hospital?.code} title="Staff"
        subtitle="Accounts for your hospital's doctors, technicians and administrators."
        actions={<Button id="staff-new-btn" onClick={() => setCreating(true)}><Icon name="plus" /> Add staff member</Button>} />

      <div className="card card--flush">
        <div className="row" style={{ padding: 16, borderBottom: "1px solid var(--border)" }}>
          <div className="segmented" role="group" aria-label="Filter by role">
            {FILTERS.map((f) => (
              <button key={f.value || "all"} type="button" className="segmented__btn" aria-pressed={role === f.value}
                id={`staff-filter-${f.value || "all"}`} onClick={() => { setRole(f.value); setPage(1); }}>
                {f.label}
              </button>
            ))}
          </div>
          <div style={{ flex: "1 1 220px", maxWidth: 320 }}>
            <label htmlFor="staff-search" className="visually-hidden">Search staff</label>
            <input id="staff-search" className="input" placeholder="Search by name or email" value={q}
              onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          {isFetching && !isLoading && <Spinner label="Refreshing" />}
        </div>

        {isLoading ? (
          <div className="page-loading" style={{ minHeight: 200 }}><Spinner /></div>
        ) : isError ? (
          <div style={{ padding: 16 }}><Alert kind="error">{errorMessage(error)}</Alert></div>
        ) : data.items.length === 0 ? (
          <EmptyState icon="users" title="No staff members found">
            <p>{q || role ? "Try a different search or filter." : "Add your first doctor or technician."}</p>
          </EmptyState>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Name</th><th>Role</th><th>Status</th><th>Last sign in</th><th className="table__actions">Actions</th></tr>
                </thead>
                <tbody>
                  {data.items.map((m) => {
                    const isSelf = m.id === user.id;
                    return (
                      <tr key={m.id}>
                        <td>
                          <div className="table__primary">{m.full_name}{isSelf && <span className="faint"> (you)</span>}</div>
                          <div className="table__secondary">{m.email}{m.registration_no ? ` · Reg. ${m.registration_no}` : ""}</div>
                        </td>
                        <td>{ROLE_LABELS[m.role]}</td>
                        <td><StaffStatus user={m} /></td>
                        <td className="faint">{formatDateTime(m.last_login_at)}</td>
                        <td className="table__actions">
                          <div className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                            <Button variant="ghost" size="sm" id={`staff-reset-${m.id}`} disabled={isSelf}
                              title={isSelf ? "Use My account to change your own password" : undefined}
                              onClick={() => setPending({ kind: "reset", member: m })}>
                              <Icon name="key" size={14} /> Reset password
                            </Button>
                            <Button variant={m.is_active ? "danger" : "secondary"} size="sm" id={`staff-toggle-${m.id}`}
                              disabled={isSelf} onClick={() => setPending({ kind: "toggle", member: m })}>
                              {m.is_active ? "Deactivate" : "Reactivate"}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pagination id="staff-pagination" page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </>
        )}
      </div>

      {creating && (
        <StaffFormModal id="new-staff-modal" title="Add a staff member" onClose={() => setCreating(false)}
          onSubmit={async (payload) => {
            const res = await post("/hospital/staff", payload);
            refresh();
            setCreating(false);
            setSecret({ title: "Staff account created", name: res.user.full_name, email: res.user.email, password: res.temp_password });
          }} />
      )}

      {pending && (
        <ConfirmDialog id="staff-action-dialog" loading={action.isPending}
          danger={pending.kind === "toggle" && pending.member.is_active}
          title={pending.kind === "reset" ? `Reset password for ${pending.member.full_name}?`
            : pending.member.is_active ? `Deactivate ${pending.member.full_name}?` : `Reactivate ${pending.member.full_name}?`}
          confirmLabel={pending.kind === "reset" ? "Reset password" : pending.member.is_active ? "Deactivate" : "Reactivate"}
          onCancel={() => { setPending(null); action.reset(); }}
          onConfirm={() => action.mutate(pending)}>
          {pending.kind === "reset"
            ? "A new temporary password is generated and their current password stops working. They must choose a new one at next sign in. This also unlocks a locked account."
            : pending.member.is_active
              ? "They will be signed out at their next request and cannot sign in. Their past actions stay in the audit log."
              : "They will be able to sign in again with their existing password."}
          {action.isError && <div style={{ marginTop: 12 }}><Alert kind="error">{errorMessage(action.error)}</Alert></div>}
        </ConfirmDialog>
      )}

      {secret && (
        <SecretDialog id="staff-temp-password" title={secret.title} secret={secret.password}
          label={`Temporary password for ${secret.name} (${secret.email}). They sign in at the hospital login with code ${user.hospital?.code}.`}
          onClose={() => setSecret(null)} />
      )}
    </>
  );
}
