# Project Context (condensed from Week 1, 2, 4 documents)

**Project:** Longitudinal Multimodal AI for Early Prediction of Melanoma Progression and Treatment Response
**Team:** Aaditya Rajvinod (R23EF004), Sriram (R23EA122) · **Mentor:** Dr. Satheesha T.Y.
The full extracted text is in [source_docs/](source_docs/).

## Core idea
Of the ABCDE rule, **Evolution** is the criterion that one photograph cannot assess. The system
therefore predicts progression from **2+ dermoscopic images of the same lesion over time**,
as *decision support* for a dermatologist, never a replacement.

## Domain vocabulary
- **Dermoscopy 7-point checklist:** Major criteria (2 points each): atypical pigment network, blue-whitish veil,
  atypical vascular pattern. Minor criteria (1 point each): irregular streaks, irregular dots/globules,
  irregular blotches, regression structures. A total of 3 or more is suspicious.
- **Follow-up:** visits every ~3 months (short-term) or 6-12 months (long-term). "Stable" comes
  from follow-up; "progressed" comes from biopsy / histopathology.
- **Fitzpatrick skin type I-VI:** used for fairness subgroups (relevant for Indian skin types).
- **3D-TBP:** 3D total-body photography (optional modality).

## Datasets (training is the ML team's job; listed here for reports and model cards)
HAM10000 (10,015 images, lesion_id), ISIC Basel SDDI1 (116 lesions × 5 serial images, the only
public serial set), SIIM-ISIC 2020 (33,126, patient IDs), ISIC 2024 SLICE-3D (401,059 TBP crops),
Derm7pt (1,011 cases, 7-point labels). Most are licensed **CC BY-NC**, so research use only.

## Pipeline modules (Week 4)
| ID | Module | Core/Cond. | Web platform touchpoint |
|---|---|---|---|
| M1 | Image Acquisition | Core | Upload endpoint, hash dedupe, visit linking |
| M2 | Preprocessing & quality | Core | quality_score / quality_flags shown on upload |
| M3 | Lesion Segmentation | Core | Mask overlay; doctor mask correction |
| M4 | Cross-Visit Registration | Core | registration_transform; warning banner |
| M5 | Temporal Features | Core | Embedding cache (ml-service side) |
| M6 | 3D Analysis | Conditional | `3d_tbp` modality; "proxy" never shown as measured |
| M7 | Multimodal Fusion (GRU + attention) | Core | attention_weights → visit-attention chart |
| M8 | Progression Prediction | Core | risk_score, risk_category |
| M9 | Treatment Response | Conditional | treatment_events; response class |
| M10 | Explainable AI | Core | difference map, Grad-CAM++, change summary |
| M11 | Uncertainty & Referral | Core | referral_flag, reason_codes |
| S1 | Fairness & Calibration Monitor | Core | /reports/subgroup-performance page |
| S2 | Clinician Dashboard | Core | Doctor portal |
| S3 | Audit Logger | Core | audit_log table + viewer |

Risk categories: `routine_monitoring`, `shortened_interval`, `specialist_referral`.
Reason codes: `low_image_quality`, `registration_uncertain`, `model_disagreement`,
`out_of_distribution`, `model_error`, `segmentation_low_confidence`.
Treatment response: `favourable`, `persistent`, `progression`, `pending`.

## Functional requirements (Week 2)
FR-01 ingest serial images linked by patient/lesion/visit timestamp · FR-02 3D-TBP (cond.) ·
FR-03 segmentation · FR-04 registration · FR-05 temporal change features · FR-06 calibrated risk ·
FR-07 monitoring category · FR-08 treatment response (cond.) · FR-09 temporal attention viz ·
FR-10 difference map · FR-11 uncertainty + mandatory review flag · FR-12 subgroup metrics ·
FR-13 clinician dashboard · FR-14 capture guidance (cond.) · FR-15 audit logging.

## Non-functional requirements
NFR-01 <60 s inference · NFR-02 scalable · NFR-03 fail-safe to referral · NFR-04 every category
explained · NFR-05 fairness monitored · NFR-06 de-identified, encrypted, access-controlled ·
NFR-07 DICOM/FHIR · NFR-08 usable without ML expertise · NFR-09 modular models · NFR-10 auditable.

## Week 4 entity list (the web DB extends this)
Patient, Lesion, Visit, Image, Prediction, Explanation, TreatmentEvent, AuditLog, User.
