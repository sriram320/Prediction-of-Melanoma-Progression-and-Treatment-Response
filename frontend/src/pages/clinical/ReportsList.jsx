import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { get, qs } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import Icon from "../../components/Icon.jsx";
import { Alert, Badge, Button, EmptyState, PageHeader, Pagination, Spinner } from "../../components/ui.jsx";
import { REPORT_STATUS, RISK_CATEGORIES } from "../../utils/clinical.js";
import { downloadPath } from "../../utils/files.js";
import { errorMessage, formatDate } from "../../utils/format.js";
import { useCan, usePortalBase } from "./portal.js";

const FILTERS = [
  { value: "", label: "All" },
  { value: "draft", label: "Drafts" },
  { value: "signed", label: "Signed" },
  { value: "released", label: "Released" },
  { value: "amended", label: "Replaced" },
];

/** Reports table. With `patientId` it is embedded in a patient record (no header or filters). */
export function ReportsTable({ patientId, status = "", page = 1, onPage, pageSize = 20 }) {
  const base = usePortalBase();
  const can = useCan();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const { data, isLoading, isError, error: loadError } = useQuery({
    queryKey: ["reports", patientId || "all", status, page],
    queryFn: () => get(`/reports${qs({ patient_id: patientId, status, page, page_size: pageSize })}`),
    placeholderData: keepPreviousData,
  });
  // Technicians can only download the patient copy of released reports; the other roles open the report page.
  const open = (r) => (can.viewAiResults ? navigate(`${base}/reports/${r.id}`) : null);
  const download = async (r) => {
    setError("");
    try { await downloadPath(`/reports/${r.id}/pdf?variant=patient&download=true`, `${r.report_number}.pdf`); }
    catch (err) { setError(errorMessage(err)); }
  };

  if (isLoading) return <div className="page-loading" style={{ minHeight: 160 }}><Spinner /></div>;
  if (isError) return <Alert kind="error">{errorMessage(loadError)}</Alert>;
  if (data.items.length === 0) {
    return (
      <EmptyState icon="report" title="No reports">
        <p>{can.writeReports ? "Review an AI result on a lesion page, then choose Create report." : "Released reports appear here."}</p>
      </EmptyState>
    );
  }
  return (
    <>
      {error && <div style={{ padding: 16 }}><Alert kind="error">{error}</Alert></div>}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>Report</th>{!patientId && <th>Patient</th>}<th>Lesion</th><th>Category</th><th>Status</th><th>Signed</th>
              {!can.viewAiResults && <th className="table__actions">PDF</th>}</tr>
          </thead>
          <tbody>
            {data.items.map((r) => {
              const st = REPORT_STATUS[r.status] || { label: r.status };
              return (
                <tr key={r.id} className={can.viewAiResults ? "is-clickable" : undefined} onClick={() => open(r)}>
                  <td>
                    {can.viewAiResults
                      ? <Link to={`${base}/reports/${r.id}`} className="table__primary mono" id={`report-link-${r.id}`}
                        onClick={(e) => e.stopPropagation()}>{r.report_number}</Link>
                      : <span className="table__primary mono">{r.report_number}</span>}
                    <div className="table__secondary">version {r.version}</div>
                  </td>
                  {!patientId && (
                    <td>
                      <div className="table__primary">{r.patient_name}</div>
                      <div className="table__secondary mono">{r.mrn}</div>
                    </td>
                  )}
                  <td>{r.lesion_label || "–"}</td>
                  <td>{r.final_category ? RISK_CATEGORIES[r.final_category].label : <span className="faint">Not set</span>}</td>
                  <td><Badge kind={st.kind} dot>{st.label}</Badge></td>
                  <td className="faint">{r.signed_at ? `${formatDate(r.signed_at)} · ${r.signed_by_name}` : "–"}</td>
                  {!can.viewAiResults && (
                    <td className="table__actions">
                      <Button variant="ghost" size="sm" id={`report-download-${r.id}`} onClick={() => download(r)}>Download</Button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {onPage && <Pagination id="reports-pagination" page={page} pageSize={pageSize} total={data.total} onPage={onPage} />}
    </>
  );
}

export default function ReportsList() {
  const { user } = useAuth();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  return (
    <>
      <PageHeader eyebrow={user.hospital?.code} title="Reports"
        subtitle="Draft, signed and released reports. Patients see a report only after it is released." />
      <div className="card card--flush">
        <div className="row" style={{ padding: 16, borderBottom: "1px solid var(--border)" }}>
          <div className="segmented" role="group" aria-label="Filter by status">
            {FILTERS.map((f) => (
              <button key={f.value || "all"} type="button" className="segmented__btn" aria-pressed={status === f.value}
                id={`reports-filter-${f.value || "all"}`} onClick={() => { setStatus(f.value); setPage(1); }}>
                {f.label}
              </button>
            ))}
          </div>
          <span className="faint row" style={{ gap: 6, fontSize: "0.85rem" }}>
            <Icon name="info" size={14} /> New reports start from a reviewed AI result on a lesion page.
          </span>
        </div>
        <ReportsTable status={status} page={page} onPage={setPage} />
      </div>
    </>
  );
}
