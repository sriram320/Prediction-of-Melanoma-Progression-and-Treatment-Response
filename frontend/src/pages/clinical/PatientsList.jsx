import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, qs } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import Icon from "../../components/Icon.jsx";
import { Alert, Badge, Button, EmptyState, PageHeader, Pagination, Spinner } from "../../components/ui.jsx";
import { fitzpatrickShort, sexLabel } from "../../utils/clinical.js";
import { errorMessage, formatDate } from "../../utils/format.js";
import PatientFormModal from "./PatientFormModal.jsx";
import { usePortalBase } from "./portal.js";

const PAGE_SIZE = 20;

export default function PatientsList() {
  const { user } = useAuth();
  const base = usePortalBase();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["patients", q, page],
    queryFn: () => get(`/patients${qs({ q, page, page_size: PAGE_SIZE })}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader eyebrow={user.hospital?.code} title="Patients"
        subtitle="Search the register, or register a new patient before recording their first visit."
        actions={<Button id="patients-new-btn" onClick={() => setCreating(true)}><Icon name="plus" /> Register patient</Button>} />

      <div className="card card--flush">
        <div className="row" style={{ padding: 16, borderBottom: "1px solid var(--border)" }}>
          <div style={{ flex: "1 1 280px", maxWidth: 380 }}>
            <label htmlFor="patients-search" className="visually-hidden">Search patients</label>
            <input id="patients-search" className="input" placeholder="Search by name, MRN or pseudonym"
              value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          {isFetching && !isLoading && <Spinner label="Refreshing" />}
        </div>

        {isLoading ? (
          <div className="page-loading" style={{ minHeight: 200 }}><Spinner /></div>
        ) : isError ? (
          <div style={{ padding: 16 }}><Alert kind="error">{errorMessage(error)}</Alert></div>
        ) : data.items.length === 0 ? (
          <EmptyState icon="patients" title={q ? "No patients match your search" : "No patients yet"}>
            {!q && <p>Register the first patient to start tracking their lesions.</p>}
          </EmptyState>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Patient</th><th>Age · sex</th><th>Skin type</th><th>Lesions</th><th>Last visit</th><th>Portal</th></tr>
                </thead>
                <tbody>
                  {data.items.map((p) => (
                    <tr key={p.id} className="is-clickable" onClick={() => navigate(`${base}/patients/${p.id}`)}>
                      <td>
                        <Link to={`${base}/patients/${p.id}`} className="table__primary" id={`patient-link-${p.id}`}
                          onClick={(e) => e.stopPropagation()}>{p.full_name}</Link>
                        <div className="table__secondary mono">{p.mrn} · {p.pseudonym_id}</div>
                      </td>
                      <td>{p.age_band || "–"} · {sexLabel(p.sex)}</td>
                      <td className="faint">{fitzpatrickShort(p.fitzpatrick_type)}</td>
                      <td>{p.lesion_count}</td>
                      <td className="faint">{formatDate(p.last_visit_date)}</td>
                      <td>{p.has_account ? <Badge kind="success" dot>Active</Badge> : <Badge>Not set up</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination id="patients-pagination" page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </>
        )}
      </div>

      {creating && (
        <PatientFormModal onClose={() => setCreating(false)} onSaved={(p) => {
          queryClient.invalidateQueries({ queryKey: ["patients"] });
          queryClient.invalidateQueries({ queryKey: ["hospital", "stats"] });
          setCreating(false);
          navigate(`${base}/patients/${p.id}`, { state: { justRegistered: true } });
        }} />
      )}
    </>
  );
}
