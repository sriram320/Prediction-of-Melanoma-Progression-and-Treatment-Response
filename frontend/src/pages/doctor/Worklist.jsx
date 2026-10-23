import { useAuth } from "../../auth/AuthContext.jsx";
import { ComingSoon, PageHeader } from "../../components/ui.jsx";
import { HospitalStats } from "../hospital-admin/Dashboard.jsx";

export default function Worklist() {
  const { user } = useAuth();
  return (
    <>
      <PageHeader eyebrow={user.hospital?.name} title="Worklist"
        subtitle="Lesions waiting for your review. Referred cases (the model was not confident) are always listed first." />
      <div className="stack stack--lg">
        <HospitalStats idPrefix="doctor-worklist" />
        <ComingSoon phase="P3–P4" icon="clipboard" title="Review queue"
          items={[
            "Analyses waiting for review, referrals first",
            "Lesion analysis view: registered visits side by side, difference map, visit attention",
            "Confirm or override the AI category, with a reason",
            "Correct the lesion outline when segmentation confidence is low",
            "Write, sign and release the report",
          ]} />
      </div>
    </>
  );
}
