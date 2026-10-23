import { useAuth } from "../../auth/AuthContext.jsx";
import { ComingSoon, PageHeader } from "../../components/ui.jsx";

export default function TechnicianHome() {
  const { user } = useAuth();
  return (
    <>
      <PageHeader eyebrow={user.hospital?.name} title="Patients"
        subtitle="Register patients, record visits and upload their scans and documents." />
      <ComingSoon phase="P2" icon="patients" title="Patient records and uploads"
        items={[
          "Search and register patients (identity is stored separately from clinical data)",
          "Create a patient invite code for the patient portal",
          "Add lesions and dated visits",
          "Drag-and-drop scan upload with an image-quality check",
          "Upload lab reports, prescriptions and histopathology documents",
        ]} />
    </>
  );
}
