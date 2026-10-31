import { useState } from "react";
import { Link } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { get, qs } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import { Alert, Badge, EmptyState, PageHeader, Pagination, Spinner } from "../../components/ui.jsx";
import { JOB_STATUS } from "../../utils/clinical.js";
import { errorMessage, formatDate, formatDateTime } from "../../utils/format.js";
import { usePortalBase } from "./portal.js";

const PAGE_SIZE = 20;
const FILTERS = [
  { value: "", label: "All" },
  { value: "running", label: "Running" },
  { value: "queued", label: "Queued" },
  { value: "succeeded", label: "Complete" },
  { value: "failed", label: "Failed" },
];

/** Analysis jobs across the hospital: progress only, never results. */
export default function JobsPage() {
  const { user } = useAuth();
  const base = usePortalBase();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["jobs", status, page],
    queryFn: () => get(`/jobs${qs({ status, page, page_size: PAGE_SIZE })}`),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items?.some((j) => ["queued", "running"].includes(j.status)) ? 3000 : false),
  });

  return (
    <>
      <PageHeader eyebrow={user.hospital?.code} title="Analysis jobs"
        subtitle="AI analyses requested in your hospital. Start a new one from a lesion's page with Run analysis." />
      <div className="card card--flush">
        <div className="row" style={{ padding: 16, borderBottom: "1px solid var(--border)" }}>
          <div className="segmented" role="group" aria-label="Filter by status">
            {FILTERS.map((f) => (
              <button key={f.value || "all"} type="button" className="segmented__btn" aria-pressed={status === f.value}
                id={`jobs-filter-${f.value || "all"}`} onClick={() => { setStatus(f.value); setPage(1); }}>
                {f.label}
              </button>
            ))}
          </div>
          {isFetching && !isLoading && <Spinner label="Refreshing" />}
        </div>
        {isLoading ? (
          <div className="page-loading" style={{ minHeight: 200 }}><Spinner /></div>
        ) : isError ? (
          <div style={{ padding: 16 }}><Alert kind="error">{errorMessage(error)}</Alert></div>
        ) : data.items.length === 0 ? (
          <EmptyState icon="activity" title="No analysis jobs">
            <p>Open a lesion with scans from at least one visit and choose Run analysis.</p>
          </EmptyState>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Patient</th><th>Lesion</th><th>Up to visit</th><th>Status</th><th>Requested</th><th>Finished</th></tr>
                </thead>
                <tbody>
                  {data.items.map((j) => {
                    const s = JOB_STATUS[j.status] || { label: j.status };
                    return (
                      <tr key={j.id}>
                        <td>
                          <Link to={`${base}/patients/${j.patient_id}`} className="table__primary" id={`job-patient-${j.id}`}>{j.patient_name}</Link>
                          <div className="table__secondary mono">{j.mrn}</div>
                        </td>
                        <td><Link to={`${base}/lesions/${j.lesion_id}`} id={`job-lesion-${j.id}`}>{j.lesion_label}</Link></td>
                        <td className="faint">{formatDate(j.visit_date)}</td>
                        <td><Badge kind={s.kind} dot>{s.label}</Badge></td>
                        <td>
                          <div>{formatDateTime(j.created_at)}</div>
                          {j.requested_by_name && <div className="table__secondary">by {j.requested_by_name}</div>}
                        </td>
                        <td className="faint">{formatDateTime(j.finished_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pagination id="jobs-pagination" page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </>
        )}
      </div>
    </>
  );
}
