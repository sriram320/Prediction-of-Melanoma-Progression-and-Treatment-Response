import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { get, qs } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import Icon from "../../components/Icon.jsx";
import { Alert, Badge, EmptyState, PageHeader, Pagination, Spinner, StatCard } from "../../components/ui.jsx";
import { REASON_CODES, RISK_CATEGORIES, siteLabel } from "../../utils/clinical.js";
import { errorMessage, formatDate, formatDateTime } from "../../utils/format.js";

const PAGE_SIZE = 20;

function Priority({ item }) {
  if (item.referral_flag) {
    return (
      <span className="worklist__priority worklist__priority--referral" title={item.reason_codes.map((r) => REASON_CODES[r] || r).join(", ")}>
        <Icon name="alert" size={15} /> Needs review: no AI category
      </span>
    );
  }
  const c = RISK_CATEGORIES[item.risk_category];
  return (
    <span className={`worklist__priority worklist__priority--${c.tone}`}>
      <Icon name={c.icon} size={15} /> {c.label}
    </span>
  );
}

export default function Worklist() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [state, setState] = useState("pending");
  const [page, setPage] = useState(1);
  const stats = useQuery({ queryKey: ["hospital", "stats"], queryFn: () => get("/hospital/stats") });
  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["worklist", state, page],
    queryFn: () => get(`/worklist${qs({ state, page, page_size: PAGE_SIZE })}`),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });

  return (
    <>
      <PageHeader eyebrow={user.hospital?.name} title="Worklist"
        subtitle="Each lesion's latest AI result waiting for your review. Referred cases, where the model gave no category, come first." />
      <div className="stat-grid" style={{ marginBottom: 20 }}>
        <StatCard label="Awaiting your review" value={stats.data?.pending_reviews} tone={stats.data?.pending_reviews ? "warn" : undefined} />
        <StatCard label="Referred by the model" value={stats.data?.open_referrals} tone={stats.data?.open_referrals ? "alert" : undefined}
          note="No AI category; needs a dermatologist" />
        <StatCard label="Reports released" value={stats.data?.reports_released} />
      </div>

      <div className="card card--flush">
        <div className="row" style={{ padding: 16, borderBottom: "1px solid var(--border)" }}>
          <div className="segmented" role="group" aria-label="Worklist view">
            {[["pending", "To review"], ["reviewed", "Reviewed"]].map(([value, label]) => (
              <button key={value} type="button" className="segmented__btn" aria-pressed={state === value}
                id={`worklist-${value}`} onClick={() => { setState(value); setPage(1); }}>{label}</button>
            ))}
          </div>
          {isFetching && !isLoading && <Spinner label="Refreshing" />}
        </div>
        {isLoading ? (
          <div className="page-loading" style={{ minHeight: 200 }}><Spinner /></div>
        ) : isError ? (
          <div style={{ padding: 16 }}><Alert kind="error">{errorMessage(error)}</Alert></div>
        ) : data.items.length === 0 ? (
          <EmptyState icon="check" title={state === "pending" ? "Nothing to review" : "No reviews yet"}>
            <p>{state === "pending" ? "New AI results appear here when an analysis finishes." : "Results you review appear here."}</p>
          </EmptyState>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{state === "pending" ? "AI result" : "Your category"}</th><th>Patient</th><th>Lesion</th>
                    <th>Up to visit</th>{state === "pending" ? <th className="num">Risk</th> : <th>Reviewed</th>}
                    <th>Analysed</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((i) => (
                    <tr key={i.prediction_id} className="is-clickable" onClick={() => navigate(`/doctor/lesions/${i.lesion_id}`)}>
                      <td>
                        {state === "pending" ? <Priority item={i} /> : (
                          <Badge kind={RISK_CATEGORIES[i.final_category].tone} dot>{RISK_CATEGORIES[i.final_category].label}</Badge>
                        )}
                      </td>
                      <td>
                        <Link to={`/doctor/lesions/${i.lesion_id}`} className="table__primary" id={`worklist-${i.prediction_id}`}
                          onClick={(e) => e.stopPropagation()}>{i.patient_name}</Link>
                        <div className="table__secondary mono">{i.mrn}</div>
                      </td>
                      <td>
                        <div>{i.lesion_label}</div>
                        <div className="table__secondary">{siteLabel(i.anatomical_site)}</div>
                      </td>
                      <td className="faint">{formatDate(i.visit_date)}</td>
                      {state === "pending"
                        ? <td className="num">{i.risk_score != null ? i.risk_score.toFixed(2) : "–"}</td>
                        : <td className="faint">{formatDateTime(i.reviewed_at)}<div className="table__secondary">{i.reviewer_name}</div></td>}
                      <td className="faint">{formatDateTime(i.analysed_at)}{i.is_mock && <div className="table__secondary">mock model</div>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination id="worklist-pagination" page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </>
        )}
      </div>
    </>
  );
}
