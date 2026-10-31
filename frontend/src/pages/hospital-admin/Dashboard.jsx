import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import { MonthlyColumns } from "../../components/charts.jsx";
import Icon from "../../components/Icon.jsx";
import { Alert, Button, PageHeader, StatCard } from "../../components/ui.jsx";
import PageLoading from "../../components/PageLoading.jsx";
import { RISK_CATEGORIES } from "../../utils/clinical.js";
import { errorMessage } from "../../utils/format.js";

export function HospitalStats({ idPrefix }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["hospital", "stats"],
    queryFn: () => get("/hospital/stats"),
    refetchInterval: 60_000,
  });
  if (isLoading) return <PageLoading />;
  if (isError) return <Alert kind="error">{errorMessage(error)}</Alert>;
  return (
    <div className="stat-grid" id={`${idPrefix}-stats`}>
      <StatCard label="Patients" value={data.patients} />
      <StatCard label="Lesions tracked" value={data.lesions} />
      <StatCard label="Visits recorded" value={data.visits} />
      <StatCard label="Awaiting doctor review" value={data.pending_reviews} tone={data.pending_reviews ? "warn" : undefined} />
      <StatCard label="Open referrals" value={data.open_referrals} tone={data.open_referrals ? "alert" : undefined}
        note="Model was not confident; needs a dermatologist" />
      <StatCard label="Reports released" value={data.reports_released} />
    </div>
  );
}

const RESULT_ROWS = [
  { key: "routine_monitoring", ...RISK_CATEGORIES.routine_monitoring },
  { key: "shortened_interval", ...RISK_CATEGORIES.shortened_interval },
  { key: "specialist_referral", ...RISK_CATEGORIES.specialist_referral },
  { key: "referral", label: "Referred without a category", tone: "referral", icon: "alert" },
  { key: "baseline", label: "Baseline only (one visit)", tone: "baseline", icon: "info" },
  { key: "not_analysed", label: "Not analysed yet", tone: "none", icon: "lesion" },
];

/** Each lesion's newest AI result, by category. Category is carried by icon and label, not colour alone. */
function CurrentResults({ current }) {
  const max = Math.max(1, ...RESULT_ROWS.map((r) => current[r.key] || 0));
  const total = RESULT_ROWS.reduce((n, r) => n + (current[r.key] || 0), 0);
  return (
    <section className="card" aria-labelledby="current-results-title">
      <h2 id="current-results-title" className="card__title">Current AI results</h2>
      <p className="faint" style={{ fontSize: "0.85rem", marginBottom: 14 }}>
        The newest result of each of {total} lesion{total === 1 ? "" : "s"}, before doctor review.
      </p>
      <ul className="result-bars">
        {RESULT_ROWS.map((r) => {
          const n = current[r.key] || 0;
          return (
            <li key={r.key} className={`result-bars__row result-bars__row--${r.tone}`}>
              <span className="result-bars__label"><Icon name={r.icon} size={15} /> {r.label}</span>
              <span className="result-bars__track" aria-hidden="true">
                {n > 0 && <span className="result-bars__bar" style={{ width: `${(n / max) * 100}%` }} />}
              </span>
              <span className="result-bars__value">{n}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const SERIES = [
  { key: "visits", title: "Visits recorded", unit: "Visits" },
  { key: "analyses", title: "AI analyses", unit: "Analyses" },
  { key: "reviews", title: "Doctor reviews", unit: "Reviews" },
  { key: "reports_released", title: "Reports released", unit: "Reports" },
];
const MONTH_YEAR = new Intl.DateTimeFormat("en-IN", { month: "short", year: "numeric" });

function Activity({ months }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="card" aria-labelledby="activity-title">
      <div className="card__header">
        <div>
          <h2 id="activity-title" className="card__title">Activity, last {months.length} months</h2>
          <p className="faint" style={{ fontSize: "0.85rem" }}>Visits by visit date; the rest by when they happened.</p>
        </div>
        <Button variant="ghost" size="sm" id="activity-toggle-table" onClick={() => setAsTable((v) => !v)}>
          {asTable ? "Show charts" : "Show as table"}
        </Button>
      </div>
      {asTable ? (
        <div className="table-wrap">
          <table className="table table--compact" id="activity-table">
            <thead><tr><th>Month</th>{SERIES.map((s) => <th key={s.key} className="num">{s.title}</th>)}</tr></thead>
            <tbody>
              {months.map((m) => (
                <tr key={m.month}>
                  <td>{MONTH_YEAR.format(new Date(`${m.month}-01T00:00:00`))}</td>
                  {SERIES.map((s) => <td key={s.key} className="num">{m[s.key]}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="small-multiples">
          {SERIES.map((s) => (
            <figure key={s.key} className="small-multiples__item">
              <figcaption className="small-multiples__title">
                {s.title} <span className="faint">· {months.reduce((n, m) => n + m[s.key], 0)}</span>
              </figcaption>
              <MonthlyColumns data={months} dataKey={s.key} unit={s.unit} id={`activity-${s.key}`} />
            </figure>
          ))}
        </div>
      )}
    </section>
  );
}

function hoursLabel(h) {
  if (h == null) return "–";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} days`;
}

export default function Dashboard() {
  const { user } = useAuth();
  const { data: activity, isLoading, isError, error } = useQuery({
    queryKey: ["hospital", "activity"],
    queryFn: () => get("/hospital/activity?months=12"),
    refetchInterval: 120_000,
  });
  const overrideRate = activity?.scored_reviews_90d
    ? `${Math.round((activity.overrides_90d / activity.scored_reviews_90d) * 100)}%` : "–";

  return (
    <>
      <PageHeader eyebrow={user.hospital?.code} title={user.hospital?.name || "Dashboard"}
        subtitle="An overview of your hospital's activity on MelanoTrack." />
      <div className="stack stack--lg">
        <HospitalStats idPrefix="hospital-dashboard" />
        {isLoading && <PageLoading />}
        {isError && <Alert kind="error">{errorMessage(error)}</Alert>}
        {activity && (
          <>
            <div className="dashboard-grid">
              <CurrentResults current={activity.current_results} />
              <section className="card" aria-labelledby="review-title">
                <h2 id="review-title" className="card__title">Doctor review, last 90 days</h2>
                <div className="stat-grid stat-grid--2" style={{ marginTop: 12 }}>
                  <StatCard label="Median time to first review" value={hoursLabel(activity.review_median_hours_90d)}
                    note="From the AI result to the first review" />
                  <StatCard label="AI category changed" value={overrideRate}
                    note={`${activity.overrides_90d} of ${activity.scored_reviews_90d} reviewed results with a category`} />
                </div>
                <div className="row" style={{ marginTop: 16 }}>
                  <Link to="/hospital/fairness" className="btn btn--secondary btn--sm" id="dashboard-fairness-link">
                    <Icon name="scale" size={15} /> Fairness report
                  </Link>
                  <Link to="/hospital/audit" className="btn btn--ghost btn--sm" id="dashboard-audit-link">
                    <Icon name="audit" size={15} /> Audit log
                  </Link>
                </div>
              </section>
            </div>
            <Activity months={activity.months} />
          </>
        )}
        <div className="card">
          <div className="row row--between">
            <div>
              <h2 className="card__title">Staff accounts</h2>
              <p className="muted" style={{ fontSize: "0.9rem" }}>Add doctors and technicians, reset passwords and deactivate leavers.</p>
            </div>
            <Link to="/hospital/staff" className="btn btn--secondary" id="dashboard-manage-staff">
              <Icon name="users" /> Manage staff
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
