// Labels for clinical enums. Values mirror backend/app/schemas/records.py.

export const ANATOMICAL_SITES = [
  { value: "head_neck", label: "Head & neck" },
  { value: "anterior_torso", label: "Front of torso" },
  { value: "posterior_torso", label: "Back" },
  { value: "lateral_torso", label: "Side of torso" },
  { value: "upper_extremity", label: "Arm or hand" },
  { value: "lower_extremity", label: "Leg or foot" },
  { value: "palms_soles", label: "Palm or sole" },
  { value: "oral_genital", label: "Oral or genital" },
  { value: "unknown", label: "Not recorded" },
];

export const DOCUMENT_CATEGORIES = [
  { value: "lab_report", label: "Lab report" },
  { value: "prescription", label: "Prescription" },
  { value: "histopathology", label: "Histopathology" },
  { value: "discharge_summary", label: "Visit / discharge summary" },
  { value: "referral_letter", label: "Referral letter" },
  { value: "consent_form", label: "Consent form" },
  { value: "imaging_other", label: "Other imaging" },
  { value: "other", label: "Other" },
];

export const SEX_OPTIONS = [
  { value: "female", label: "Female" },
  { value: "male", label: "Male" },
  { value: "other", label: "Other" },
  { value: "unknown", label: "Not recorded" },
];

export const FITZPATRICK = [
  { value: 1, label: "I - always burns, never tans" },
  { value: 2, label: "II - usually burns, tans minimally" },
  { value: 3, label: "III - sometimes burns, tans gradually" },
  { value: 4, label: "IV - rarely burns, tans easily" },
  { value: 5, label: "V - very rarely burns, tans darkly" },
  { value: 6, label: "VI - never burns, deeply pigmented" },
];

export const MODALITIES = [
  { value: "dermoscopic", label: "Dermoscopic" },
  { value: "clinical_photo", label: "Clinical photo" },
  { value: "3d_tbp", label: "3D total-body photo" },
];

export const QUALITY_FLAGS = {
  blur: "Possibly blurred",
  glare: "Glare",
  too_dark: "Too dark",
  overexposed: "Overexposed",
  low_resolution: "Low resolution",
};

export const MEDICAL_HISTORY = [
  { key: "prior_melanoma", label: "Previous melanoma" },
  { key: "family_history_melanoma", label: "Family history of melanoma" },
  { key: "many_naevi", label: "More than 50 moles" },
  { key: "immunosuppressed", label: "Immunosuppressed" },
];

const ROMAN = ["", "I", "II", "III", "IV", "V", "VI"];
const lookup = (list, value) => list.find((o) => o.value === value)?.label ?? value ?? "–";

export const siteLabel = (v) => lookup(ANATOMICAL_SITES, v);
export const categoryLabel = (v) => lookup(DOCUMENT_CATEGORIES, v);
export const sexLabel = (v) => lookup(SEX_OPTIONS, v);
export const modalityLabel = (v) => lookup(MODALITIES, v);
export const fitzpatrickShort = (v) => (v ? `Type ${ROMAN[v]}` : "Skin type not recorded");

// ---------- AI results (doctors and hospital admins only) ----------
export const RISK_CATEGORIES = {
  routine_monitoring: { label: "Routine monitoring", tone: "routine", icon: "check" },
  shortened_interval: { label: "Shortened follow-up interval", tone: "shortened", icon: "clock" },
  specialist_referral: { label: "Specialist referral recommended", tone: "referral", icon: "alert" },
};

export const REASON_CODES = {
  low_image_quality: "Image quality too low",
  registration_uncertain: "Visits could not be aligned reliably",
  model_disagreement: "Model uncertainty is high",
  out_of_distribution: "Images unlike the model's training data",
  model_error: "The model could not produce a result",
  segmentation_low_confidence: "Lesion outline is uncertain",
  ambiguous_prediction: "Result sits on a category boundary",
};

export const RISK_THRESHOLDS = [0.35, 0.65];

const FEATURES = {
  area_relative_to_baseline: { label: "Area vs first visit", format: (v) => `${v.toFixed(2)}×` },
  colour_variation: { label: "Colour variation", format: (v) => v.toFixed(2) },
  asymmetry: { label: "Asymmetry", format: (v) => v.toFixed(2) },
  border_irregularity: { label: "Border irregularity", format: (v) => v.toFixed(2) },
};

export function featureLabel(key) {
  return FEATURES[key]?.label || key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export function formatFeature(key, value) {
  if (value == null) return "–";
  return FEATURES[key] ? FEATURES[key].format(value) : Number(value).toFixed(3);
}

export const JOB_STATUS = {
  queued: { label: "Queued", kind: "accent" },
  running: { label: "Running", kind: "accent" },
  succeeded: { label: "Complete", kind: "success" },
  failed: { label: "Failed", kind: "danger" },
  cancelled: { label: "Cancelled", kind: undefined },
};

// ---------- Reports and review ----------
export const PATIENT_CATEGORY = {
  routine_monitoring: { label: "No changes that need action now", tone: "routine", icon: "check" },
  shortened_interval: { label: "An earlier follow-up visit is recommended", tone: "shortened", icon: "clock" },
  specialist_referral: { label: "A specialist should examine this spot", tone: "referral", icon: "alert" },
};

export const REPORT_STATUS = {
  draft: { label: "Draft", kind: undefined },
  pending_review: { label: "Draft", kind: undefined },
  signed: { label: "Signed, not released", kind: "accent" },
  released: { label: "Released to patient", kind: "success" },
  amended: { label: "Replaced by a newer version", kind: "warning" },
};

export const RECOMMENDATION_PRESETS = [
  "Routine skin check in 12 months",
  "Follow-up visit in 3 months",
  "Follow-up visit in 6 months",
  "See a dermatologist within 2 weeks",
];

export const TREATMENT_TYPES = [
  { value: "excision", label: "Excision" },
  { value: "shave_biopsy", label: "Shave biopsy" },
  { value: "punch_biopsy", label: "Punch biopsy" },
  { value: "cryotherapy", label: "Cryotherapy" },
  { value: "topical_therapy", label: "Topical therapy" },
  { value: "immunotherapy", label: "Immunotherapy" },
  { value: "targeted_therapy", label: "Targeted therapy" },
  { value: "radiotherapy", label: "Radiotherapy" },
  { value: "other", label: "Other" },
];
export const treatmentLabel = (v) => TREATMENT_TYPES.find((t) => t.value === v)?.label ?? v;

// Only tissue-sampling procedures carry a result (backend HISTOPATHOLOGY_TYPES).
export const HISTOPATHOLOGY_TYPES = ["excision", "shave_biopsy", "punch_biopsy"];
export const HISTOPATHOLOGY = [
  { value: "", label: "Result not back yet" },
  { value: "melanoma", label: "Melanoma" },
  { value: "not_melanoma", label: "Not melanoma" },
];
export const histopathologyLabel = (v) => HISTOPATHOLOGY.find((h) => h.value === (v || ""))?.label ?? v;
