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
| `GET /audit?entity_type&entity_id&user_id&from&to` | SA, HA(own hospital) | |
| `GET /audit/{predictionId}` | SA HA DR | |
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

## 4. Audit actions (use these exact strings)
`auth.login`, `auth.login_failed`, `auth.logout`, `user.create`, `user.update`, `patient.create`,
`patient.update`, `patient.invite`, `patient.activate`, `file.upload`, `file.read`, `visit.create`,
`visit.exclude`, `mask.update`, `job.create`, `prediction.create`, `prediction.review`,
`report.create`, `report.sign`, `report.release`, `report.amend`, `report.download`,
`document.visibility`, `model.activate`, `hospital.create`, `hospital.update` (P1), `lesion.create` (P2).
Patient changes log field names only, never values.
`app/services/audit.py` rejects any action not in this list.

## 5. Notes
- A patient user is created at the registering hospital. A patient record at a second hospital is a separate
  `patients` row; linking multiple records to one login is out of scope for v1.
- Upload validation: check magic bytes (Pillow / pydicom / PDF header), strip EXIF, max 50 MB.
- DICOM upload: convert to PNG for viewing and the model, keep the original encrypted, and map
  `ManufacturerModelName` to `visits.device_model` when it is empty.
