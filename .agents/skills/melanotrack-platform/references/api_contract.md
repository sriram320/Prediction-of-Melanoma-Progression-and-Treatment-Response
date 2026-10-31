# API Contract (v1)

Base: `/api/v1` · JSON · errors use `{"detail": "...", "code": "SNAKE_CASE"}` · times are ISO-8601 UTC.
Pagination: `?page=1&page_size=20` → `{"items": [...], "total": n, "page": 1, "page_size": 20}`.

## 1. Authentication

### Tokens
- **Access token:** JWT HS256, 15 min, held in memory by the SPA and sent as `Authorization: Bearer`.
  Claims: `sub` (user_id), `role`, `hid` (hospital_id | null), `pid` (patient_id, patients only), `exp`, `jti`.
- **Refresh token:** opaque random 256-bit value, 7 days, in cookie `mt_refresh`
  (`HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`). Only the sha256 is stored. It is rotated on every
  refresh; if a revoked token is reused, the whole `family_id` is revoked.
- **Lockout:** 5 failed attempts lead to a 15-minute lock. Login is rate-limited to 10/min per IP.

| Method & path | Body | Notes |
|---|---|---|
| `POST /auth/hospital/login` | `{hospital_code, email, password}` | Roles: hospital_admin, doctor, technician. Fails if the hospital is inactive. |
| `POST /auth/patient/login` | `{identifier, password}` | identifier = email or phone |
| `POST /auth/admin/login` | `{email, password}` | super_admin only |
| `POST /auth/patient/activate` | `{invite_code, date_of_birth, email?, phone?, password}` | Creates the patient user and links `patients.user_id` |
| `POST /auth/refresh` | cookie | → `{access_token, user}` |
| `POST /auth/logout` | cookie | Revokes the refresh family |
| `GET /auth/me` | – | `{id, role, full_name, hospital:{id,name,code}?, patient_id?, must_change_password}` |
| `POST /auth/change-password` | `{current_password, new_password}` | Clears `must_change_password` |

Login response: `{access_token, token_type:"bearer", expires_in:900, user:{...me}}` + Set-Cookie.
`me` also includes `email` and `phone`. Login bodies take the email as a plain string (no format validation,
so a typo gives `INVALID_CREDENTIALS`, not 422); account-creation bodies validate emails strictly.

**Implemented behaviour (P1):**
- `must_change_password` ⇒ every endpoint except `/auth/me`, `/auth/change-password`, `/auth/logout` returns
  403 `PASSWORD_CHANGE_REQUIRED`. Seeded super admin and every temp-password account start in this state.
- Refresh reuse grace: a token rotated less than `REFRESH_REUSE_GRACE_S` (10 s) ago, while its family still has a
  live token, returns 401 `REFRESH_RACE` (cookie kept; the SPA retries once). This covers two tabs refreshing at the
  same moment. Any other reuse returns `TOKEN_REUSED` and revokes the family.
- Inactive hospital ⇒ its staff and patients get 403 `HOSPITAL_INACTIVE` at login and on every request.
- Password rule: 10-128 chars, at least one letter and one digit (`WEAK_PASSWORD` 422).

**Error codes:** `INVALID_CREDENTIALS` 401, `ACCOUNT_LOCKED` 423, `ACCOUNT_INACTIVE` 403, `HOSPITAL_INACTIVE` 403,
`PASSWORD_CHANGE_REQUIRED` 403, `INVALID_TOKEN` 401, `NO_SESSION` 401, `SESSION_EXPIRED` 401, `TOKEN_REUSED` 401,
`REFRESH_RACE` 401, `WRONG_PASSWORD` 400, `WEAK_PASSWORD` 422, `INVALID_INVITE` 400, `ALREADY_ACTIVATED` 409,
`IDENTIFIER_TAKEN` 409, `EMAIL_TAKEN` 409, `CODE_TAKEN` 409, `CANNOT_DEACTIVATE_SELF` 400, `RATE_LIMITED` 429,
`FORBIDDEN` 403, `NOT_FOUND` 404, `VALIDATION_ERROR` 422 (+ `errors:[{field,message}]`).

## 2. FastAPI dependencies (implement in `app/core/deps.py`)
```python
current_user = Depends(get_current_user)              # decodes JWT, loads user, checks is_active
require_roles(*roles)                                 # 403 if role not allowed
get_scope(user) -> Scope(hospital_id, patient_id|None, role)
scope.filter(stmt, Model)                             # adds hospital_id / patient_id predicates
```
**Rule:** if a resource belongs to another hospital, return **404** (not 403) so that its existence is not leaked.

## 3. Endpoints and permissions
Legend: SA super_admin · HA hospital_admin · DR doctor · TE technician · PT patient

### Super admin
| Endpoint | Roles | Notes |
|---|---|---|
| `GET/POST /admin/hospitals` | SA | create `{code,name,address,contact_email,contact_phone}`; list `?q=&page=` adds `staff_count`, `patient_count` |
| `GET /admin/hospitals/{id}` | SA | hospital + counts + `admins[]` (added in P1) |
| `PATCH /admin/hospitals/{id}` | SA | includes `is_active` |
| `POST /admin/hospitals/{id}/admins` | SA | `{full_name,email,phone?}` → `{user, temp_password}` (password shown once) |

### Hospital admin
| `GET/POST /hospital/staff` | HA | list `?role=&q=&page=`; create `{role∈[hospital_admin,doctor,technician], full_name, email, phone?, registration_no?}` → `{user, temp_password}` |
| `PATCH /hospital/staff/{id}` | HA | `{full_name?, phone?, registration_no?, is_active?, reset_password?}` → `{user, temp_password?}`; reset also unlocks; cannot deactivate self |
| `GET /hospital/stats` | HA, DR | `{patients, lesions, visits, pending_reviews, open_referrals, reports_released, staff}` |

### Patients
| `GET /patients?q=` | HA DR TE | search by name / MRN / pseudonym |
| `POST /patients` | HA DR TE | `{mrn, full_name, date_of_birth, sex, phone?, email?, address?, fitzpatrick_type?, medical_history?, consent_status}` → computes age_band and pseudonym_id |
| `GET /patients/{id}` | HA DR TE, PT(self) | identity + clinical summary + lesions |
| `PATCH /patients/{id}` | HA DR TE | |
| `POST /patients/{id}/invite` | HA DR TE | → `{invite_code, expires_at}` (shown once, valid 7 days) |

### Lesions, visits, images
| `GET /patients/{id}/lesions` | HA DR TE PT(self) | |
| `POST /patients/{id}/lesions` | HA DR TE | `{label, anatomical_site}` |
| `GET /lesions/{id}/timeline` | HA DR TE PT(self) | visits in date order with images, latest prediction (**omitted for TE, PT**), reviews, treatment events |
| `POST /lesions/{id}/visits` | HA DR TE | `{visit_date, device_model?, illumination?, polarised?, notes?}`; future dates rejected |
| `POST /visits/{id}/images` | HA DR TE | multipart `files[]`, `modality`; → per-file `{image_id, duplicate:boolean, quality_score, quality_flags}` |
| `PUT /images/{id}/mask` | DR | PNG mask upload or `{confirm:true}` → sets mask_confirmed_by |
| `PATCH /visits/{id}` | DR | `{excluded:true, reason}` (clinician-confirmed exclusion) |

### Documents & files
| `GET /patients/{id}/documents` | HA DR TE, PT(self, visible only) | |
| `POST /patients/{id}/documents` | HA DR TE | multipart `file`, `category`, `title`, `document_date?`, `lesion_id?`, `visible_to_patient` |
| `PATCH /documents/{id}` | HA DR | toggle visibility |
| `GET /files/{id}/content` | access derived from the owning image/document/report | streams decrypted bytes; `Content-Disposition`; audited |
| `GET /files/{id}/thumbnail?size=256` | same | cached encrypted thumbnail |

### Analysis
| `POST /lesions/{id}/analyze` | DR TE | `{visit_id?}` (default latest) → **202** `{job_id, status:"queued"}`; 409 if a job is already queued/running |
| `GET /jobs/{id}` | DR TE | `{status, error?, prediction_id?}` |
| `GET /predictions/{id}` | HA DR | full prediction + `model:{name,version,is_mock}` |
| `GET /predictions/{id}/explanation` | HA DR | `{attention_weights, difference_map_file_id, saliency_file_id, change_summary[], registration_warning}` |
| `POST /predictions/{id}/review` | DR | `{decision, final_category, reason}`; reason required if overridden **or** if the prediction was referred |
| `GET/POST /lesions/{id}/treatment-events` | DR | `{treatment_type, treatment_date, notes}` |

### Reports
| `POST /reports` | DR | `{patient_id, lesion_id, prediction_id?}` → draft prefilled from review + change summary |
| `PATCH /reports/{id}` | DR | `patient_summary, doctor_notes, recommendation, final_category` (draft/pending only) |
| `POST /reports/{id}/sign` | DR | renders both PDFs (patient + clinician), status → signed |
| `POST /reports/{id}/release` | DR HA | status → released, notifies patient |
| `POST /reports/{id}/amend` | DR | creates version+1 draft with `supersedes_id` |
| `GET /reports?patient_id=` | HA DR TE | |
| `GET /reports/{id}/pdf?variant=patient|clinician` | PT(self, released, patient variant only), HA DR TE | |

### Patient portal (`PT`, always scoped to token `pid`)
| `GET /me/overview` | `{patient, lesion_count, latest_report?, upcoming_followup?}` |
| `GET /me/lesions` | lesions + visits + image ids (no predictions) |
| `GET /me/documents` | visible documents only |
| `GET /me/reports` | released reports only |

### Monitoring
| `GET /reports/subgroup-performance?from&to` | SA HA DR | grouped by fitzpatrick_type, anatomical_site, device_model, illumination: n, referral_rate, override_rate, mean_risk, sensitivity/specificity (when histopathology outcome is known) |
| `GET /audit?action&entity_type&entity_id&user_id&hospital_id&from&to` | SA, HA(own hospital) | see P5 below |
| `GET /audit/{predictionId}` | SA HA DR | |
| `POST /audit/verify` | SA | hash-chain check (P5) |
| `GET /hospital/activity?months` | HA DR | monthly counts and current results (P5) |
| `GET /lesions/{id}/predictions` | HA DR | prediction history for the risk trend (P5) |
| `GET /models` / `POST /models` / `POST /models/{id}/activate` | SA | |
| `GET /health` | public | `{status, db:"ok", ml_service:"ok"\|"unavailable", model:{name,version,is_mock}}`; if no active model can be read, `is_mock:true` (fail-safe: watermark stays on) |

### Implemented behaviour (P2)
- **Patients use `/me/*` only.** `GET /patients/{id}`, `/patients/{id}/lesions|documents` and
  `/lesions/{id}/timeline` are staff-only (HA DR TE); the patient portal reads `/me/overview|lesions|documents`.
- `POST /patients` body adds structured `medical_history: {prior_melanoma?, family_history_melanoma?, many_naevi?,
  immunosuppressed?, notes?}` (unknown keys rejected). `consent_at` is set when consent becomes true.
  `PatientOut` adds `has_account`, `pending_invite{expires_at}`, `lesion_count`, `document_count`.
- `POST /patients/{id}/invite` retires earlier unused codes (only the newest works); 409 `ALREADY_ACTIVATED`.
- `anatomical_site` is a fixed vocabulary (ISIC groups): `head_neck, anterior_torso, posterior_torso, lateral_torso,
  upper_extremity, lower_extremity, palms_soles, oral_genital, unknown`. Lesion labels are unique per patient.
- Visits: one per lesion per date (409 `VISIT_DATE_TAKEN`); not in the future (+1 day slack) or before DOB.
  `PATCH /visits/{id}` (DR) needs `{excluded, reason}`; the reason goes to the audit log.
- `GET /lesions/{id}/timeline` → `{lesion, patient{pseudonym_id,...}, visits[{images[]}], analysable_visit_count,
  treatment_events, latest_prediction}`; `latest_prediction` key is **absent** for technicians.
- `POST /visits/{id}/images` (≤10 files, ≤50 MB each) → `200 [{filename, image_id, file_id, duplicate,
  duplicate_visit_date, quality_score, quality_flags, error}]`. Bad files get `error`; the rest are stored.
  An identical image already in the hospital is not added again (`duplicate: true`).
  Type is detected from magic bytes. JPEG/PNG are re-encoded without EXIF/GPS/comments/XMP (ICC kept);
  TIFF → PNG; DICOM → PNG with the original kept as `images.source_file_id` (staff-only) and
  `ManufacturerModelName` copied to an empty `visits.device_model`.
- Quality flags (heuristic pre-check): `blur, glare, too_dark, overexposed, low_resolution`; visit score = min of
  its images.
- Documents: PDF/JPEG/PNG/TIFF. Technicians cannot set `visible_to_patient` (403). Same file twice for one patient →
  409 `DUPLICATE_DOCUMENT`.
- Files: `GET /files/{id}/content?download=` and `/thumbnail?size=128|256|512` (JPEG). Access comes from what the
  file is attached to (scan image → staff / owning patient; document → staff / patient if shared). Anything else
  → 404 until its phase adds a rule. Every read (thumbnails too) writes `file.read` with `details.variant`.
  Headers: `Cache-Control: private, no-store`, `nosniff`, `CSP: sandbox`.
- New error codes: `MRN_TAKEN` 409, `LABEL_TAKEN` 409, `VISIT_DATE_TAKEN` 409, `TOO_MANY_FILES` 422,
  `INVALID_FILE` 422, `DUPLICATE_DOCUMENT` 409, `NO_THUMBNAIL` 415, `FILE_UNAVAILABLE` 500 (missing/tampered).

### Implemented behaviour (P3)
- `POST /lesions/{id}/analyze` (DR TE) → 202 `{job_id, status}`. 409 `CONSENT_REQUIRED` (no recorded consent),
  409 `NO_SCANS`, 422 `VISIT_NOT_ANALYSABLE` (given visit excluded or without scans), 409 `JOB_IN_PROGRESS`,
  503 `NO_ACTIVE_MODEL`. Uses non-excluded visits with scans up to the trigger visit (default: latest).
- `GET /jobs?lesion_id=&status=&page=` (HA DR TE) lists jobs with patient, lesion and visit date.
  `GET /jobs/{id}`: technicians get progress only; HA/DR also get `prediction_id` and `error`.
- A model failure does **not** fail the job: the job `succeeded` with a `model_error` referral stored and `error`
  set. `failed` means no prediction at all (scan unreadable, retries exhausted).
- `GET /predictions/{id}` → adds `visit_date`, `visit_features[{visit_id, visit_date, features, melanoma_probability}]`,
  `model_error`, `reviewed`. `GET /predictions/{id}/explanation` adds `saliency_passed_check`.
- Timeline: `latest_job{id,status,...}` for all staff; `latest_prediction` (full PredictionOut) for HA/DR only.
- Files: masks and explanation maps are readable by HA/DR only (technicians and patients get 404).
- Predictions are append-only history; stats count only each lesion's newest prediction.
- `GET /health` adds `ml_model{name,version,is_mock}` and `model_match`.

### Implemented behaviour (P4)
- `POST /predictions/{id}/review` (DR) body `{final_category, reason?}`: the decision is **derived**: `confirmed` when
  final_category equals the AI category, otherwise `overridden`. A reason (>= 3 chars) is required when overridden,
  which includes every referral and baseline (422 `REASON_REQUIRED`). Reviews are history; the newest counts.
  `GET /predictions/{id}/reviews` (HA DR). `PredictionOut.latest_review`.
- `GET /worklist?state=pending|reviewed` (HA DR): each lesion's newest prediction. Pending = unreviewed and (scored or
  referred), ordered referral first, then specialist > shortened > routine, then oldest.
- `PUT /images/{id}/mask` (DR), multipart: `confirm=true` (409 `NO_MASK` if none) or `file` = PNG outline (any size
  with the scan's aspect ratio; resized; must not be empty or full; 422 `INVALID_FILE`). Sets `mask_confirmed_by`,
  confidence 1.0 for drawn outlines. Timeline `ImageOut` gains `mask_file_id, mask_confidence, mask_confirmed` (HA/DR only).
- `GET/POST /lesions/{id}/treatment-events`: list for staff, create for DR. Types: excision, shave_biopsy, punch_biopsy,
  cryotherapy, topical_therapy, immunotherapy, targeted_therapy, radiotherapy, other.
- Reports: `POST /reports {lesion_id, prediction_id?}` (default: the lesion's newest prediction) creates a draft prefilled
  from the review (category, plain-language summary template, recommendation) and the AI change summary (doctor notes);
  409 `DRAFT_EXISTS`. Numbers `MT-YYYY-NNNNNN` (sequence), amendments `-V2`…
  `PATCH` only while draft (409 `REPORT_LOCKED`); `final_category` is not editable when linked to a prediction (422
  `CATEGORY_FROM_REVIEW`). `/sign` (DR): 409 `REVIEW_REQUIRED`, 422 `INCOMPLETE_REPORT`. `/release` (DR HA): signed
  only (409 `NOT_SIGNED` / `ALREADY_RELEASED`); marks the superseded version `amended`. `/amend` (DR): signed/released
  only, one amendment (409 `AMENDMENT_EXISTS`).
- `GET /reports?patient_id&lesion_id&status` and `GET /reports/{id}`: technicians get released reports only, without
  doctor notes or model. `GET /reports/{id}/pdf?variant=patient|clinician&download=`: patients (own, released, patient
  copy), technicians (released, patient copy), HA/DR (both). Audited as `report.download`.
- `GET /me/reports` (released only; doctor's words, no AI fields); `/me/overview.latest_report`.
- Audit action added: `treatment.create`.

### Implemented behaviour (P5)
- Treatments: `POST /lesions/{id}/treatment-events` accepts `histopathology: melanoma|not_melanoma|null`, and
  `PATCH /treatment-events/{id} {histopathology}` (DR) records or clears it later. Only excision / shave_biopsy /
  punch_biopsy (422 `HISTOPATHOLOGY_NOT_APPLICABLE`). Audited as `treatment.update` with field names only.
  `TreatmentOut` and timeline `treatment_events[]` gain `histopathology` (+ `histopathology_recorded_at` in TreatmentOut).
  The value is never sent to the ml-service.
- `GET /lesions/{id}/predictions` (HA DR): every prediction of the lesion, oldest first, with visit date, model,
  score/category/uncertainty/referral and the newest review (`review_decision`, `final_category`). Feeds the risk trend.
- `GET /hospital/activity?months=1..24` (HA DR, default 12): per month (DISPLAY_TIMEZONE) `visits` (by visit_date),
  `analyses`, `reviews`, `reports_released`; `current_results` (each lesion's newest result: the three categories,
  `referral`, `baseline`, plus `not_analysed` active lesions); `awaiting_review`; last 90 days `scored_reviews_90d`,
  `overrides_90d` (results with an AI category only) and `review_median_hours_90d` (result -> first review).
- `GET /reports/subgroup-performance?from&to&hospital_id` (SA HA DR; `hospital_id` honoured for SA only, staff get their
  own hospital; registered before `/reports/{id}`). Unit: each lesion's newest non-baseline prediction created in the
  period. Per row: `n, small_sample (n<10), referral_n/rate, scored_n, mean_risk, routine_n/shortened_n/specialist_n,
  reviewed_scored_n, override_n/rate, outcome_n, melanoma_n, ai{tp,fn,tn,fp,sensitivity,specificity}, after_review{…}`.
  Outcomes: the lesion's newest histopathology result, matched to its newest prediction from a visit on or before the
  procedure date. Flagged = anything but routine monitoring (shortened, specialist, or a referral). Dimensions
  `fitzpatrick_type, anatomical_site, device_model, illumination` (value `null` = not recorded) plus `overall`,
  `calibration` (5 score bins: n, mean_risk, observed_rate), `models`, `any_mock`. No patient identity in the output.
- `GET /audit?action&user_id&entity_type&entity_id&hospital_id&from&to&page&page_size<=200` (SA all hospitals, HA own):
  newest first; `action` may be a group (`report`); unknown -> 422. Entries add `actor_name`, `hospital_code`, hashes.
  For SA, `details.reason` is `[redacted]` and patient actors are unnamed. `GET /audit/actions` (SA HA).
- `GET /audit/{predictionId}` (SA HA DR): entries for the prediction, its job(s) and reports based on it.
- `POST /audit/verify` (SA): recomputes every row hash (session time zone or UTC rendering), checks each `prev_hash`
  points at an existing row and no two rows share a predecessor; returns `{ok, checked, hash_mismatches,
  missing_links, forks, first_problem_id, head_id, head_hash}`. Audited as `audit.verify`. Deleting the newest rows is
  only detectable against a head hash kept elsewhere.

## 4. Audit actions (use these exact strings)
`auth.login`, `auth.login_failed`, `auth.logout`, `user.create`, `user.update`, `patient.create`,
`patient.update`, `patient.invite`, `patient.activate`, `file.upload`, `file.read`, `visit.create`,
`visit.exclude`, `mask.update`, `job.create`, `prediction.create`, `prediction.review`,
`report.create`, `report.sign`, `report.release`, `report.amend`, `report.download`,
`document.visibility`, `model.activate`, `hospital.create`, `hospital.update` (P1), `lesion.create` (P2), `treatment.create` (P4),
`treatment.update`, `audit.verify` (P5).
Patient changes log field names only, never values.
`app/services/audit.py` rejects any action not in this list.

## 5. Notes
- A patient user is created at the registering hospital. A patient record at a second hospital is a separate
  `patients` row; linking multiple records to one login is out of scope for v1.
- Upload validation: check magic bytes (Pillow / pydicom / PDF header), strip EXIF, max 50 MB.
- DICOM upload: convert to PNG for viewing and the model, keep the original encrypted, and map
  `ManufacturerModelName` to `visits.device_model` when it is empty.
