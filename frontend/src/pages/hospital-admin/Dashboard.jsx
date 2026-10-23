import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import Icon from "../../components/Icon.jsx";
import { Alert, PageHeader, StatCard } from "../../components/ui.jsx";
import PageLoading from "../../components/PageLoading.jsx";
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

export default function Dashboard() {
  const { user } = useAuth();
  return (
    <>
      <PageHeader eyebrow={user.hospital?.code} title={user.hospital?.name || "Dashboard"}
        subtitle="An overview of your hospital's activity on MelanoTrack." />
      <HospitalStats idPrefix="hospital-dashboard" />
      <div className="card" style={{ marginTop: 24 }}>
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
    </>
  );
}
