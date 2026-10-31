// Plain-language names for audit actions. Values mirror backend/app/services/audit.py (ACTIONS).

export const ACTION_LABELS = {
  "auth.login": "Signed in",
  "auth.login_failed": "Sign-in failed",
  "auth.logout": "Signed out",
  "user.create": "Created a staff account",
  "user.update": "Changed a user account",
  "patient.create": "Registered a patient",
  "patient.update": "Edited patient details",
  "patient.invite": "Issued a patient invite code",
  "patient.activate": "Patient activated their account",
  "file.upload": "Uploaded a file",
  "file.read": "Opened a file",
  "visit.create": "Recorded a visit",
  "visit.exclude": "Changed a visit's exclusion",
  "lesion.create": "Added a lesion",
  "mask.update": "Confirmed or corrected an outline",
  "job.create": "Requested an AI analysis",
  "prediction.create": "AI result stored",
  "prediction.review": "Reviewed an AI result",
  "treatment.create": "Recorded a treatment",
  "treatment.update": "Recorded a histopathology result",
  "report.create": "Started a report",
  "report.sign": "Signed a report",
  "report.release": "Released a report to the patient",
  "report.amend": "Started an amendment",
  "report.download": "Opened a report PDF",
  "document.visibility": "Changed document sharing",
  "model.activate": "Activated a model version",
  "hospital.create": "Created a hospital",
  "hospital.update": "Changed hospital details",
  "audit.verify": "Verified the audit chain",
};

export const ACTION_GROUPS = {
  auth: "Sign-ins",
  user: "User accounts",
  patient: "Patients",
  lesion: "Lesions",
  visit: "Visits",
  file: "Files",
  mask: "Outlines",
  job: "Analysis jobs",
  prediction: "AI results and reviews",
  treatment: "Treatments",
  report: "Reports",
  document: "Documents",
  model: "Models",
  hospital: "Hospitals",
  audit: "Audit",
};

export const actionLabel = (a) => ACTION_LABELS[a] || a;

export const ENTITY_LABELS = {
  user: "User", patient: "Patient", lesion: "Lesion", visit: "Visit", image: "Image", file: "File",
  document: "Document", inference_job: "Analysis job", prediction: "AI result", treatment_event: "Treatment",
  report: "Report", hospital: "Hospital",
};

/** Detail keys shown inline in the log table; the rest are in the expanded row. */
export const DETAIL_LABELS = {
  portal: "Portal", reason: "Reason", decision: "Decision", final_category: "Final category",
  ai_category: "AI category", report_number: "Report", variant: "Copy", fields: "Fields", role: "Role",
  category: "Category", model: "Model", visible_to_patient: "Shared with patient", excluded: "Excluded",
  treatment_type: "Treatment", action: "Change", code: "Code", ok: "Chain intact", checked: "Rows checked",
};
