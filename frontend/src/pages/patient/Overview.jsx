import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../api/client.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import Icon from "../../components/Icon.jsx";
import { Alert, PageHeader, StatCard } from "../../components/ui.jsx";
import { errorMessage, formatDate } from "../../utils/format.js";

export default function PatientOverview() {
  const { user } = useAuth();
  const firstName = user.full_name.split(" ")[0];
  const { data, isError, error } = useQuery({ queryKey: ["me", "overview"], queryFn: () => get("/me/overview") });

  return (
    <>
      <PageHeader eyebrow={user.hospital?.name} title={`Hello, ${firstName}`}
        subtitle="This is your personal space for skin checks at your hospital." />
      <div className="stack stack--lg">
        {isError && <Alert kind="error">{errorMessage(error)}</Alert>}
        <div className="stat-grid">
          <StatCard label="Spots being monitored" value={data?.lesion_count} />
          <StatCard label="Visits with photos" value={data?.visit_count} />
          <StatCard label="Last visit" value={data ? formatDate(data.last_visit_date) : undefined} />
          <StatCard label="Shared documents" value={data?.document_count} />
        </div>
        <div className="row">
          <Link to="/patient/lesions" className="btn btn--primary" id="overview-scans-link"><Icon name="lesion" /> View my scans</Link>
          <Link to="/patient/documents" className="btn btn--secondary" id="overview-documents-link"><Icon name="document" /> Documents</Link>
        </div>
        <div className="card">
          <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
            <div className="empty__icon" style={{ margin: 0, flex: "none" }}><Icon name="shield" size={22} /></div>
            <div>
              <h2 className="card__title" style={{ marginBottom: 6 }}>How your results reach you</h2>
              <p className="muted">
                Your doctor reviews every comparison of your photos before anything is shared with you. A report appears
                here only after your doctor has signed and released it. If you have questions, please contact your hospital.
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
