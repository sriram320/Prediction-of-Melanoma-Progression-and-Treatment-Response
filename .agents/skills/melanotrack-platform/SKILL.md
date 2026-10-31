---
name: melanotrack-platform
description: >-
  Project memory for the MelanoTrack web platform (Longitudinal Multimodal AI for
  Early Melanoma Progression Prediction - Aaditya Rajvinod & Sriram, mentor Dr. Satheesha T.Y.).
  Use this skill for ANY work in d:\MAJOR__PROJECT_WEB_DEV: building or modifying the
  FastAPI backend, React+Vite frontend, PostgreSQL schema, encrypted file storage,
  patient/hospital logins and RBAC, AI-model integration (ModelAdapter / ml-service),
  PDF report generation, Docker Compose deployment, or answering questions about the
  project's Week 1/2/4 design documents (modules M1-M11, S1-S3, FR-xx, NFR-xx).
---

# MelanoTrack Platform Skill

A secure, multi-hospital web platform where hospital staff upload a patient's serial
lesion scans and documents, an AI model predicts melanoma progression risk, a doctor
reviews the result and signs a report, and the patient logs in to view it.

## 1. Read first (progressive disclosure)
| Need | File |
|---|---|
| What the research project is and what the design docs require (M1-M11, FR/NFR) | [references/project_context.md](references/project_context.md) |
| PostgreSQL DDL, enums, constraints, indexes | [references/database_schema.md](references/database_schema.md) |
| REST endpoints, auth flow, request/response shapes, permissions | [references/api_contract.md](references/api_contract.md) |
| Plugging in the teammates' trained model, mock adapter, safety wrapper | [references/model_integration.md](references/model_integration.md) |
| Original weekly documents (plain text + figures) | [references/source_docs/](references/source_docs/) |
| Full human-facing implementation document | [docs/Implementation_Document.md](../../../docs/Implementation_Document.md) |

## 2. Locked decisions (do not change without asking the user)
- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.0 async (asyncpg), Alembic, Pydantic v2.
- **Frontend:** React 18 + Vite, React Router, TanStack Query, Recharts, **vanilla CSS** (no Tailwind).
  Dark clinical theme: navy `hsl(222 47% 8%)`, teal accent `hsl(186 80% 48%)`, fonts Inter/Outfit.
- **DB:** PostgreSQL 16. The DB also serves as the job queue (`inference_jobs`, `FOR UPDATE SKIP LOCKED`), so there is no Redis.
- **Files:** encrypted **local disk** volume `/data/storage` (NOT MinIO, NOT DB blobs).
  AES-256-GCM per-file DEK, wrapped by `STORAGE_MASTER_KEY`. Files are never served statically.
- **Runtime:** Docker Compose services: `db`, `backend`, `worker`, `ml-service`, `frontend`, `caddy`.
  (docker-compose.yml implements `frontend` + `caddy` as one `web` container: `deploy/web.Dockerfile` builds the
  SPA and Caddy serves it and proxies `/api`.)
- **Local development (user's laptop):** native **PostgreSQL 18** on `localhost:5432` (+ pgAdmin), backend and
  ml-service in `backend/.venv` (Python 3.11), frontend via `npm run dev`. Docker is for deployment.
- **Roles (5):** `super_admin`, `hospital_admin`, `doctor`, `technician`, `patient`.
- **Two logins:** `/hospital/login` (hospital code + email + password) and `/patient/login`
  (email/phone + password). Patients are onboarded only through an invite code.

## 3. Non-negotiable invariants (from design docs; enforce in backend, never only in UI)
1. `referral_flag = true` ⇒ `risk_category IS NULL` (DB CHECK + service layer). NFR-03 / FR-11.
2. Any model error, timeout (>60 s) or invalid output ⇒ store a prediction with `referral_flag=true`,
   reason `model_error`. Never return a silent or default-benign result.
3. A lesion with a single visit ⇒ baseline only, no risk score.
4. Patients see **only** `reports.status = 'released'` and documents with `visible_to_patient = true`.
   Patients never see raw predictions.
5. Every clinical query is scoped by `hospital_id` (via the `get_scope` dependency). Patients are scoped to their own `patient_id`.
6. `audit_log` is append-only (trigger blocks UPDATE/DELETE; hash chain). Log every file access,
   prediction, review, sign, release and login.
7. The ml-service receives **de-identified** data only (pseudonym_id, age_band, sex, site, Fitzpatrick type).
8. While `MODEL_ADAPTER=mock`, the UI and PDFs show the watermark "MOCK MODEL — NOT FOR CLINICAL USE".

## 4. Repository layout
```text
backend/app/{core,models,schemas,api/v1,services,workers,templates}  backend/alembic  backend/tests
ml_service/app/{main.py,contract.py,adapters/}   ml_service/models/<name>/<version>/  (gitignored)
frontend/src/{styles,api,auth,components,layouts,pages/<portal>}
deploy/Caddyfile   docker-compose.yml   .env.example   storage/ (gitignored)
docs/Implementation_Document.md      Week1/2/4 *.docx (repo root, original design docs)
```

## 5. Common procedures
- **Local dev (native, Windows):** once: `scripts\dev\setup_local_db.ps1` (creates role/db from `.env`; asks for
  the `postgres` password). Then `scripts\dev\start_backend.ps1` (migrate + seed + uvicorn :8000),
  `scripts\dev\start_ml_service.ps1` (:8100), and `cd frontend && npm run dev` (:5173, proxies `/api`).
- **Local tests:** `cd backend && .venv\Scripts\python -m pytest -q` (creates/drops `melanotrack_test` on the server
  from `DATABASE_URL`/`.env`; role needs CREATEDB; files go to a temp folder, never to `storage/`).
- **Synthetic scans** (no real patient data): the demo seed adds a 3-visit lesion for `patient@demo.example`;
  `python -m app.scripts.synthetic <dir>` writes 3 JPEGs for trying uploads.
- **Protected files in the SPA:** never put `/api/v1/files/...` in an `<img src>` (no token is sent). Use
  `SecureImage` / `utils/files.js` (fetch with the token → blob: URL).
- **Windows Smart App Control** on the dev laptop blocks low-reputation native DLLs (greenlet 3.5.x was blocked).
  Pin known-good versions (`greenlet==3.1.1`) instead of upgrading native wheels blindly.
- **Demo accounts** (SEED_DEMO=true) use the reserved `.example` domain (`.local` fails email validation):
  super admin `admin@melanotrack.example`; DEMO01 staff `admin@ / doctor@ / tech@demo.example`; patient
  `patient@demo.example`; all with `SEED_DEMO_PASSWORD`. Invite code `DEMO-INVITE-2026` + DOB 1988-11-02.
- **Start the stack (Docker):** `docker compose up -d --build`, then check `curl http://localhost:8080/api/v1/health`.
- **New migration:** `docker compose exec backend alembic revision --autogenerate -m "<msg>"` then
  `docker compose exec backend alembic upgrade head`. Review autogenerated SQL for enums and triggers
  (Alembic does not autogenerate the triggers; write them with `op.execute`).
- **Seed super admin:** `docker compose exec backend python -m app.scripts.seed`.
- **Backend tests:** `docker compose exec backend pytest -q`.
- **Frontend dev (hot reload):** `cd frontend && npm run dev` (proxy `/api` → `http://localhost:8000`).
- **Integrate the real model:** follow [model_integration.md §5](references/model_integration.md).
- **PDF reports** use fpdf2 (pure Python). Font: `REPORT_FONT_PATH`, else DejaVu (Docker) or Arial (Windows), else core
  Helvetica (Latin-1 only). Indic-script names need a font with those glyphs (e.g. Noto Sans Kannada) via `REPORT_FONT_PATH`.
- **Charts** use Recharts via `frontend/src/components/charts.jsx` (colours read from the CSS tokens; 2px lines, r=4
  markers with a surface ring, columns <= 24px with 4px rounded ends, one axis per chart, table view or text alongside).
  Risk colours always come with an icon and a label.
- **Fairness ground truth:** doctors record histopathology on excision/biopsy treatments (Treatments card on the lesion
  page). Without it the fairness report shows rates only (no sensitivity/specificity/calibration).
- **Audit chain check:** `POST /audit/verify` (super admin, Audit log page). Tests tamper with a row by switching off
  `trg_audit_no_update` as the table owner and expect a mismatch.
- **Verify the safety wrapper:** set `MOCK_FORCE_ERROR=1` on ml-service, run analyze, and expect `referral_flag=true`.
  (Automated in `backend/tests/test_analysis.py`, which mounts the real ml-service in-process.)
- **Analysis jobs locally:** the API runs the worker itself (`EMBEDDED_WORKER=true`); start the ml-service too or every
  analysis becomes a `model_error` referral. `GET /api/v1/health` shows `model_match` (registry vs ml-service).

## 6. Coding conventions
- API prefix `/api/v1`; routers in `app/api/v1/<group>.py`; business logic lives in `app/services/`, not in routers.
- Every route declares `Depends(require_roles(...))`. Clinical routes also use `Depends(get_scope)`.
- IDs are UUIDv4 (`gen_random_uuid()`); timestamps are `timestamptz` in UTC; dates are `date` (visit_date).
- Pydantic schemas: `XCreate`, `XUpdate`, `XOut`. Never return `password_hash`, `wrapped_dek` or `storage_path`.
- Frontend: one CSS token file `src/styles/index.css`; component CSS modules or BEM classes;
  every interactive element has a unique `id`; one `<h1>` per page.
- Avoid technical ML jargon in patient-facing text (NFR-08).

## 7. Implementation status (UPDATE THIS as phases complete)
| Phase | Status |
|---|---|
| P0 Foundations (compose, skeletons, design system) | ✅ Done 2026-10-23 (native local run verified; `docker compose up` not yet run) |
| P1 Auth & tenancy | ✅ Done 2026-10-23 (20 backend tests pass; super-admin + hospital-admin consoles; other portals are shells) |
| P2 Records & encrypted files | ✅ Done 2026-10-24 (36 backend tests pass; staff patient register/record/lesion timeline/uploads/documents; patient My scans + Documents) |
| P3 Inference pipeline (mock) | ✅ Done 2026-10-31 (50 backend + 10 ml-service tests; analysis runs in ~2.6 s on the demo lesion; doctor/admin analysis panel, technician jobs page) |
| P4 Doctor review & PDF reports | ✅ Done 2026-10-31 (58 backend tests; worklist, review/override, outline editor, treatments, report editor, sign/release/amend, patient Reports page) |
| P5 Dashboards, fairness, audit viewer | ✅ Done 2026-10-31 (64 backend tests; risk trend + measurement charts, hospital activity dashboard, fairness report for SA/HA/DR with CSV export, audit viewer for SA/HA with hash-chain verification, histopathology results on biopsies/excisions; migration 0004) |
| P6 Real model integration | ⏳ Waiting for teammates' trained model |
| P7 Hardening (RLS, backups, tests, FHIR) | ⏳ Not started |

## 8. Open questions for the user (remove when answered)
- Patient login: implemented as email **or** phone + password (per api_contract). Is SMS OTP needed?
- P3 added `ambiguous_prediction` to the reason codes and optional per-visit outputs (`visits[].features`,
  `melanoma_probability`) to the contract. Per-visit Grad-CAM images are not in the contract yet: needed?
- P3 requires recorded consent before an analysis can be queued. Confirm this is the hospital policy.
- Release currently has no patient notification (no SMS/email provider). Needed? (MSG91 / Twilio / SMTP.)
- Patient names in Kannada/Devanagari script need an Indic font for PDFs. Should we ship Noto fonts?
- P5 fairness report: "flagged" = anything other than routine monitoring (shortened interval counts as flagged) and
  groups under 10 lesions are marked too small. Confirm both with the team/mentor. Should histopathology also record
  melanoma in situ / dysplastic naevus as separate classes?
- Super admin audit view hides free-text reasons and patient names. Is that the right line for the platform owner?
- Should the audit head hash be exported somewhere automatically (e.g. nightly with the backups, P7)?
- Can patients see raw scan images before a report is released? (Implemented as yes, images only, excluded
  visits hidden; never quality scores, notes or AI output. Confirm.)
- Should technicians be able to remove a wrongly uploaded image? (P2 has no delete; a doctor can exclude the visit.)
- Does the server have an NVIDIA GPU? (Decides CUDA vs CPU torch in ml-service.)
- Hosting target (lab machine / cloud VM / local demo) and domain for HTTPS.
- Keep the name "MelanoTrack"?
