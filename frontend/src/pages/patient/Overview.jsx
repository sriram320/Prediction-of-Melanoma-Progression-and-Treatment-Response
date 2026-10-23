import { useAuth } from "../../auth/AuthContext.jsx";
import Icon from "../../components/Icon.jsx";
import { ComingSoon, PageHeader } from "../../components/ui.jsx";

export default function PatientOverview() {
  const { user } = useAuth();
  const firstName = user.full_name.split(" ")[0];
  return (
    <>
      <PageHeader eyebrow={user.hospital?.name} title={`Hello, ${firstName}`}
        subtitle="This is your personal space for skin checks at your hospital." />
      <div className="stack stack--lg">
        <div className="card">
          <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
            <div className="empty__icon" style={{ margin: 0, flex: "none" }}><Icon name="shield" size={22} /></div>
            <div>
              <h2 className="card__title" style={{ marginBottom: 6 }}>How your results reach you</h2>
              <p className="muted">
                Your doctor reviews every scan comparison before anything is shared with you. You will see a report here
                only after your doctor has signed and released it. If you have questions about a report, please contact
                your hospital.
              </p>
            </div>
          </div>
        </div>
        <ComingSoon phase="P2–P4" icon="lesion" title="Your scans and reports"
          items={[
            "Your scan history for each tracked spot, by visit date",
            "Documents your hospital has shared with you",
            "Released reports, viewable and downloadable as PDF",
          ]} />
      </div>
    </>
  );
}
