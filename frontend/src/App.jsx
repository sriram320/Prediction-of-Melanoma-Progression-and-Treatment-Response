import { Route, Routes } from "react-router-dom";
import RequireAuth from "./auth/RequireAuth.jsx";
import { ComingSoon, PageHeader } from "./components/ui.jsx";
import PortalLayout from "./layouts/PortalLayout.jsx";
import Worklist from "./pages/doctor/Worklist.jsx";
import Dashboard from "./pages/hospital-admin/Dashboard.jsx";
import Staff from "./pages/hospital-admin/Staff.jsx";
import PatientOverview from "./pages/patient/Overview.jsx";
import AdminLogin from "./pages/public/AdminLogin.jsx";
import ForcedPasswordChange from "./pages/public/ForcedPasswordChange.jsx";
import HospitalLogin from "./pages/public/HospitalLogin.jsx";
import Landing from "./pages/public/Landing.jsx";
import NotFound from "./pages/public/NotFound.jsx";
import PatientActivate from "./pages/public/PatientActivate.jsx";
import PatientLogin from "./pages/public/PatientLogin.jsx";
import AccountPage from "./pages/shared/AccountPage.jsx";
import HospitalDetail from "./pages/super-admin/HospitalDetail.jsx";
import Hospitals from "./pages/super-admin/Hospitals.jsx";
import TechnicianHome from "./pages/technician/Home.jsx";

/** Placeholder page for a nav item scheduled in a later phase. */
function Planned({ title, phase, items, icon }) {
  return (
    <>
      <PageHeader title={title} />
      <ComingSoon phase={phase} title={title} items={items} icon={icon} />
    </>
  );
}

function portal(roles) {
  return (
    <RequireAuth roles={roles}>
      <PortalLayout />
    </RequireAuth>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/hospital/login" element={<HospitalLogin />} />
      <Route path="/patient/login" element={<PatientLogin />} />
      <Route path="/patient/activate" element={<PatientActivate />} />
      <Route path="/admin/login" element={<AdminLogin />} />
      <Route path="/change-password"
        element={<RequireAuth allowPasswordChange><ForcedPasswordChange /></RequireAuth>} />

      <Route path="/admin" element={portal(["super_admin"])}>
        <Route index element={<Hospitals />} />
        <Route path="hospitals/:hospitalId" element={<HospitalDetail />} />
        <Route path="models" element={<Planned title="Model versions" phase="P6" icon="model"
          items={["Register a trained model with its metrics and model card", "Activate a version (removes the mock watermark when the active model is not a mock)"]} />} />
        <Route path="audit" element={<Planned title="Audit log" phase="P5" icon="audit"
          items={["Search the append-only, hash-chained audit trail", "Verify the hash chain"]} />} />
        <Route path="account" element={<AccountPage />} />
      </Route>

      <Route path="/hospital" element={portal(["hospital_admin"])}>
        <Route index element={<Dashboard />} />
        <Route path="staff" element={<Staff />} />
        <Route path="patients" element={<Planned title="Patients" phase="P2" icon="patients"
          items={["Patient register and search", "Lesions, visits and uploads"]} />} />
        <Route path="fairness" element={<Planned title="Fairness report" phase="P5" icon="scale"
          items={["Referral and override rates by Fitzpatrick type, body site, device and illumination", "Sensitivity and specificity where histopathology is known"]} />} />
        <Route path="audit" element={<Planned title="Audit log" phase="P5" icon="audit"
          items={["Every sign-in, file access, prediction, review, signature and release in your hospital"]} />} />
        <Route path="account" element={<AccountPage />} />
      </Route>

      <Route path="/doctor" element={portal(["doctor"])}>
        <Route index element={<Worklist />} />
        <Route path="patients" element={<Planned title="Patients" phase="P2" icon="patients"
          items={["Patient register, lesion timelines and documents"]} />} />
        <Route path="reports" element={<Planned title="Reports" phase="P4" icon="report"
          items={["Draft, sign, release and amend reports", "Patient and clinician PDF versions"]} />} />
        <Route path="account" element={<AccountPage />} />
      </Route>

      <Route path="/technician" element={portal(["technician"])}>
        <Route index element={<TechnicianHome />} />
        <Route path="uploads" element={<Planned title="Uploads & jobs" phase="P3" icon="upload"
          items={["Start an analysis for a lesion", "Follow analysis jobs until they finish"]} />} />
        <Route path="account" element={<AccountPage />} />
      </Route>

      <Route path="/patient" element={portal(["patient"])}>
        <Route index element={<PatientOverview />} />
        <Route path="lesions" element={<Planned title="My scans" phase="P2" icon="lesion"
          items={["Your scan history for each tracked spot"]} />} />
        <Route path="documents" element={<Planned title="Documents" phase="P2" icon="document"
          items={["Documents your hospital has shared with you"]} />} />
        <Route path="reports" element={<Planned title="Reports" phase="P4" icon="report"
          items={["Reports your doctor has signed and released"]} />} />
        <Route path="account" element={<AccountPage />} />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
