import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post, qs } from "../../api/client.js";
import Icon from "../../components/Icon.jsx";
import { Alert, Badge, Button, EmptyState, Modal, PageHeader, Pagination, Spinner, TextInput } from "../../components/ui.jsx";
import { errorMessage, formatDate } from "../../utils/format.js";

const PAGE_SIZE = 20;

function NewHospitalModal({ onClose, onCreated }) {
  const [form, setForm] = useState({ code: "", name: "", address: "", contact_email: "", contact_phone: "" });
  const [error, setError] = useState("");
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const create = useMutation({
    mutationFn: () => post("/admin/hospitals", {
      code: form.code.trim(), name: form.name.trim(), address: form.address.trim() || null,
      contact_email: form.contact_email.trim() || null, contact_phone: form.contact_phone.trim() || null,
    }),
    onSuccess: onCreated,
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <Modal id="new-hospital-modal" title="Register a hospital" onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose} id="new-hospital-cancel">Cancel</Button>
        <Button type="submit" form="new-hospital-form" loading={create.isPending} id="new-hospital-submit"
          disabled={!form.code.trim() || !form.name.trim()}>Create hospital</Button>
      </>}>
      <form id="new-hospital-form" className="stack" noValidate
        onSubmit={(e) => { e.preventDefault(); setError(""); create.mutate(); }}>
        <Alert kind="error" id="new-hospital-error">{error}</Alert>
        <div className="form-grid">
          <TextInput id="new-hospital-code" label="Hospital code" className="input--upper" maxLength={16}
            value={form.code} onChange={set("code")} hint="3-16 letters or digits. Staff type it to sign in." required />
          <TextInput id="new-hospital-name" label="Name" value={form.name} onChange={set("name")} required />
          <div className="field--full">
            <TextInput id="new-hospital-address" label="Address" value={form.address} onChange={set("address")} />
          </div>
          <TextInput id="new-hospital-email" label="Contact email" type="email" value={form.contact_email}
            onChange={set("contact_email")} />
          <TextInput id="new-hospital-phone" label="Contact phone" type="tel" value={form.contact_phone}
            onChange={set("contact_phone")} />
        </div>
      </form>
    </Modal>
  );
}

export default function Hospitals() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["admin", "hospitals", q, page],
    queryFn: () => get(`/admin/hospitals${qs({ q, page, page_size: PAGE_SIZE })}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader eyebrow="Platform" title="Hospitals"
        subtitle="Each hospital is a separate tenant: its staff and patients are never visible to other hospitals."
        actions={<Button id="hospitals-new-btn" onClick={() => setCreating(true)}><Icon name="plus" /> New hospital</Button>} />

      <div className="card card--flush">
        <div className="row" style={{ padding: 16, borderBottom: "1px solid var(--border)" }}>
          <div style={{ flex: "1 1 280px", maxWidth: 360 }}>
            <label htmlFor="hospitals-search" className="visually-hidden">Search hospitals</label>
            <input id="hospitals-search" className="input" placeholder="Search by name or code"
              value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          {isFetching && !isLoading && <Spinner label="Refreshing" />}
        </div>

        {isLoading ? (
          <div className="page-loading" style={{ minHeight: 200 }}><Spinner /></div>
        ) : isError ? (
          <div style={{ padding: 16 }}><Alert kind="error">{errorMessage(error)}</Alert></div>
        ) : data.items.length === 0 ? (
          <EmptyState icon="hospital" title={q ? "No hospitals match your search" : "No hospitals yet"}>
            {!q && <p>Register the first hospital to start onboarding staff.</p>}
          </EmptyState>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Hospital</th><th>Code</th><th>Staff</th><th>Patients</th><th>Status</th><th>Registered</th></tr>
                </thead>
                <tbody>
                  {data.items.map((h) => (
                    <tr key={h.id} className="is-clickable" onClick={() => navigate(`/admin/hospitals/${h.id}`)}>
                      <td>
                        <Link to={`/admin/hospitals/${h.id}`} className="table__primary" id={`hospital-link-${h.code}`}
                          onClick={(e) => e.stopPropagation()}>{h.name}</Link>
                        {h.contact_email && <div className="table__secondary">{h.contact_email}</div>}
                      </td>
                      <td className="mono">{h.code}</td>
                      <td>{h.staff_count}</td>
                      <td>{h.patient_count}</td>
                      <td>{h.is_active ? <Badge kind="success" dot>Active</Badge> : <Badge kind="danger" dot>Inactive</Badge>}</td>
                      <td className="faint">{formatDate(h.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination id="hospitals-pagination" page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </>
        )}
      </div>

      {creating && (
        <NewHospitalModal onClose={() => setCreating(false)} onCreated={(h) => {
          queryClient.invalidateQueries({ queryKey: ["admin", "hospitals"] });
          setCreating(false);
          navigate(`/admin/hospitals/${h.id}`);
        }} />
      )}
    </>
  );
}
