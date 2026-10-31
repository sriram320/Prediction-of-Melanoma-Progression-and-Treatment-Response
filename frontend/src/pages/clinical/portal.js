import { useAuth } from "../../auth/AuthContext.jsx";

const BASE = { hospital_admin: "/hospital", doctor: "/doctor", technician: "/technician" };

/** Staff portals share the record pages; links stay inside the current portal. */
export function usePortalBase() {
  const { user } = useAuth();
  return BASE[user.role];
}

export function useCan() {
  const { user } = useAuth();
  return {
    shareDocuments: user.role === "hospital_admin" || user.role === "doctor",
    excludeVisits: user.role === "doctor",
    runAnalysis: user.role === "doctor" || user.role === "technician",
    viewAiResults: user.role === "doctor" || user.role === "hospital_admin",
    review: user.role === "doctor",
    writeReports: user.role === "doctor",
    releaseReports: user.role === "doctor" || user.role === "hospital_admin",
  };
}
