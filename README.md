# MelanoTrack

Web platform for the project *Longitudinal Multimodal AI for Early Prediction of Melanoma Progression and
Treatment Response* (Aaditya Rajvinod, Sriram · mentor Dr. Satheesha T.Y.).

Hospital staff upload a patient's serial lesion scans, an AI model estimates progression risk, a doctor reviews and
signs a report, and the patient sees the released report. **AI decision support only, not a diagnosis.**
The design is in [docs/Implementation_Document.md](docs/Implementation_Document.md).

## Run locally (Windows, native PostgreSQL)

Prerequisites: PostgreSQL (tested with 18) running on `localhost:5432`, Python 3.11 (`py -3.11`), Node 20+.

1. **Environment.** `.env` holds local secrets and is never committed. To start fresh, copy `.env.example` and
   fill in the secrets (the comments explain how to generate each one).
2. **Database, once.** This creates the `melanotrack` role and database with the password from `.env`. It asks for
   your `postgres` superuser password and does not store it:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\dev\setup_local_db.ps1
   ```
   (Or in pgAdmin: create a login role `melanotrack` with *Can login* + *Create databases* and the
   `POSTGRES_PASSWORD` from `.env`, then a database `melanotrack` owned by it.)
3. **Backend** (migrates, seeds, serves on :8000):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\dev\start_backend.ps1
   ```
4. **ml-service** (:8100), in a second terminal:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\dev\start_ml_service.ps1
   ```
5. **Frontend** (:5173), in a third terminal:
   ```powershell
   cd frontend; npm install; npm run dev
   ```
   Open http://localhost:5173. API docs: http://localhost:8000/api/docs.

### Demo accounts (created when `SEED_DEMO=true`)

| Portal | Login | Password |
|---|---|---|
| Platform admin (`/admin/login`) | `admin@melanotrack.example` | `SEED_SUPERADMIN_PASSWORD`, changed at first sign in |
| Hospital (`/hospital/login`), code `DEMO01` | `admin@demo.example`, `doctor@demo.example`, `tech@demo.example` | `SEED_DEMO_PASSWORD` |
| Patient (`/patient/login`) | `patient@demo.example` or `+919800000001` | `SEED_DEMO_PASSWORD` |
| Patient activation (`/patient/activate`) | invite `DEMO-INVITE-2026`, date of birth `1988-11-02` | you choose |

The demo seed also gives `patient@demo.example` a lesion with three visits of **synthetic** scans (no real patient
data) and two documents, one of them shared with the patient. To try uploading, generate sample scans with
`backend\.venv\Scripts\python -m app.scripts.synthetic sample_scans` (run from `backend`).

### Running an AI analysis

Open a lesion that has scans (as a doctor or technician) and choose **Run analysis**. The API runs the job queue
itself, so the ml-service (step 4) must be running; if it is not, the result is a referral with "The model could not
produce a result", never a silent default. Doctors and hospital admins see the result and explanation maps; technicians
see progress only. The model is a **mock** until the team's trained model is plugged in (see
`.agents/skills/melanotrack-platform/references/model_integration.md`).

### Tests

```powershell
cd backend; .venv\Scripts\python -m pytest -q
cd ..\ml_service; ..\backend\.venv\Scripts\python -m pytest -q tests
```
The suite uses the database server from `.env`, but creates and drops its own `melanotrack_test` database and stores
files in a temporary folder, so your development data is never touched.

## Deploy with Docker

`docker compose up -d --build`, then open http://localhost:8080. Compose runs its own PostgreSQL 16 container.

## Never commit

`.env`, `storage/`, or model weights in `ml_service/models/`.
