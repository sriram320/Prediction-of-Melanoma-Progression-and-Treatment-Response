-- MelanoTrack initial schema. Mirrors .agents/skills/melanotrack-platform/references/database_schema.md
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TYPE user_role         AS ENUM ('super_admin','hospital_admin','doctor','technician','patient');
CREATE TYPE image_modality    AS ENUM ('dermoscopic','clinical_photo','3d_tbp');
CREATE TYPE risk_category     AS ENUM ('routine_monitoring','shortened_interval','specialist_referral');
CREATE TYPE job_status        AS ENUM ('queued','running','succeeded','failed','cancelled');
CREATE TYPE report_status     AS ENUM ('draft','pending_review','signed','released','amended');
CREATE TYPE response_category AS ENUM ('favourable','persistent','progression','pending');
CREATE TYPE review_decision   AS ENUM ('confirmed','overridden');
CREATE TYPE document_category AS ENUM ('lab_report','prescription','histopathology',
        'discharge_summary','referral_letter','consent_form','imaging_other','other');
CREATE TYPE lesion_status     AS ENUM ('active','excised','closed');
CREATE TYPE sex_type          AS ENUM ('male','female','other','unknown');

CREATE SEQUENCE report_number_seq START 1;

CREATE TABLE hospitals (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code          varchar(16) UNIQUE NOT NULL,
  name          varchar(200) NOT NULL,
  address       text,
  contact_email citext,
  contact_phone varchar(20),
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  hospital_id          uuid REFERENCES hospitals(id),
  role                 user_role NOT NULL,
  email                citext,
  phone                varchar(20),
  password_hash        text NOT NULL,
  full_name            varchar(200) NOT NULL,
  registration_no      varchar(50),
  is_active            boolean NOT NULL DEFAULT true,
  must_change_password boolean NOT NULL DEFAULT true,
  failed_login_count   int NOT NULL DEFAULT 0,
  locked_until         timestamptz,
  last_login_at        timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CHECK ((role = 'super_admin') = (hospital_id IS NULL)),
  CHECK (email IS NOT NULL OR phone IS NOT NULL)
);
CREATE UNIQUE INDEX ux_users_staff_email   ON users(hospital_id, email) WHERE role <> 'patient';
CREATE UNIQUE INDEX ux_users_patient_email ON users(email) WHERE role = 'patient' AND email IS NOT NULL;
CREATE UNIQUE INDEX ux_users_patient_phone ON users(phone) WHERE role = 'patient' AND phone IS NOT NULL;
CREATE UNIQUE INDEX ux_users_super_email   ON users(email) WHERE role = 'super_admin';

CREATE TABLE refresh_tokens (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  char(64) UNIQUE NOT NULL,
  family_id   uuid NOT NULL,
  expires_at  timestamptz NOT NULL,
  revoked_at  timestamptz,
  ip          varchar(45),
  user_agent  text,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_refresh_family ON refresh_tokens(family_id);

CREATE TABLE patients (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  hospital_id      uuid NOT NULL REFERENCES hospitals(id),
  user_id          uuid UNIQUE REFERENCES users(id),
  mrn              varchar(50) NOT NULL,
  pseudonym_id     varchar(20) UNIQUE NOT NULL,
  sex              sex_type NOT NULL DEFAULT 'unknown',
  age_band         varchar(10),
  fitzpatrick_type smallint CHECK (fitzpatrick_type BETWEEN 1 AND 6),
  medical_history  jsonb NOT NULL DEFAULT '{}',
  consent_status   boolean NOT NULL DEFAULT false,
  consent_at       timestamptz,
  created_by       uuid REFERENCES users(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (hospital_id, mrn)
);

CREATE TABLE patient_identity (
  patient_id    uuid PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE,
  full_name     varchar(200) NOT NULL,
  date_of_birth date NOT NULL,
  phone         varchar(20),
  email         citext,
  address       text
);
CREATE INDEX ix_identity_name ON patient_identity (lower(full_name));

CREATE TABLE patient_invites (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id  uuid NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  code_hash   char(64) NOT NULL,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  created_by  uuid REFERENCES users(id),
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_invites_code ON patient_invites(code_hash);

CREATE TABLE stored_files (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  hospital_id       uuid NOT NULL REFERENCES hospitals(id),
  sha256            char(64) NOT NULL,
  size_bytes        bigint NOT NULL,
  mime_type         varchar(100) NOT NULL,
  original_filename varchar(255),
  storage_path      text NOT NULL,
  enc_algo          varchar(20) NOT NULL DEFAULT 'AES-256-GCM',
  wrapped_dek       bytea NOT NULL,
  nonce             bytea NOT NULL,
  key_version       smallint NOT NULL DEFAULT 1,
  uploaded_by       uuid REFERENCES users(id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (hospital_id, sha256)
);

CREATE TABLE lesions (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id          uuid NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  hospital_id         uuid NOT NULL REFERENCES hospitals(id),
  label               varchar(50) NOT NULL,
  anatomical_site     varchar(50) NOT NULL,
  status              lesion_status NOT NULL DEFAULT 'active',
  first_seen_visit_id uuid,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_lesions_patient ON lesions(patient_id);

CREATE TABLE visits (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lesion_id      uuid NOT NULL REFERENCES lesions(id) ON DELETE CASCADE,
  hospital_id    uuid NOT NULL REFERENCES hospitals(id),
  visit_date     date NOT NULL,
  device_model   varchar(100),
  illumination   varchar(30),
  polarised      boolean,
  quality_score  real,
  quality_flags  jsonb NOT NULL DEFAULT '[]',
  excluded       boolean NOT NULL DEFAULT false,
  notes          text,
  created_by     uuid REFERENCES users(id),
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_visits_timeline ON visits(lesion_id, visit_date);
ALTER TABLE lesions ADD CONSTRAINT fk_first_visit
  FOREIGN KEY (first_seen_visit_id) REFERENCES visits(id) ON DELETE SET NULL;

CREATE TABLE images (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  visit_id               uuid NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
  hospital_id            uuid NOT NULL REFERENCES hospitals(id),
  modality               image_modality NOT NULL,
  file_id                uuid NOT NULL REFERENCES stored_files(id),
  mask_file_id           uuid REFERENCES stored_files(id),
  mask_confidence        real,
  mask_confirmed_by      uuid REFERENCES users(id),
  registration_transform jsonb,
  registration_quality   real,
  width                  int,
  height                 int,
  quality_score          real,
  quality_flags          jsonb NOT NULL DEFAULT '[]',
  created_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_images_visit ON images(visit_id);

CREATE TABLE documents (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id         uuid NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  hospital_id        uuid NOT NULL REFERENCES hospitals(id),
  lesion_id          uuid REFERENCES lesions(id),
  file_id            uuid NOT NULL REFERENCES stored_files(id),
  category           document_category NOT NULL,
  title              varchar(200) NOT NULL,
  document_date      date,
  visible_to_patient boolean NOT NULL DEFAULT false,
  uploaded_by        uuid REFERENCES users(id),
  created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_documents_patient ON documents(patient_id, document_date DESC);

CREATE TABLE treatment_events (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lesion_id         uuid NOT NULL REFERENCES lesions(id) ON DELETE CASCADE,
  hospital_id       uuid NOT NULL REFERENCES hospitals(id),
  treatment_type    varchar(50) NOT NULL,
  treatment_date    date NOT NULL,
  response_category response_category NOT NULL DEFAULT 'pending',
  notes             text,
  created_by        uuid REFERENCES users(id),
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_versions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          varchar(50) NOT NULL,
  version       varchar(30) NOT NULL,
  adapter       varchar(50) NOT NULL,
  is_mock       boolean NOT NULL DEFAULT false,
  metrics       jsonb NOT NULL DEFAULT '{}',
  model_card    text,
  is_active     boolean NOT NULL DEFAULT false,
  registered_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version)
);
CREATE UNIQUE INDEX ux_one_active_model ON model_versions(is_active) WHERE is_active;

CREATE TABLE inference_jobs (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lesion_id        uuid NOT NULL REFERENCES lesions(id) ON DELETE CASCADE,
  hospital_id      uuid NOT NULL REFERENCES hospitals(id),
  trigger_visit_id uuid NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
  model_version_id uuid REFERENCES model_versions(id),
  status           job_status NOT NULL DEFAULT 'queued',
  attempts         smallint NOT NULL DEFAULT 0,
  error            text,
  prediction_id    uuid,
  requested_by     uuid REFERENCES users(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  started_at       timestamptz,
  finished_at      timestamptz
);
CREATE INDEX ix_jobs_queue ON inference_jobs(created_at) WHERE status = 'queued';

CREATE TABLE predictions (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  visit_id           uuid NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
  lesion_id          uuid NOT NULL REFERENCES lesions(id) ON DELETE CASCADE,
  hospital_id        uuid NOT NULL REFERENCES hospitals(id),
  job_id             uuid REFERENCES inference_jobs(id) ON DELETE SET NULL,
  model_version_id   uuid NOT NULL REFERENCES model_versions(id),
  is_baseline        boolean NOT NULL DEFAULT false,
  risk_score         numeric(5,4) CHECK (risk_score BETWEEN 0 AND 1),
  risk_category      risk_category,
  change_score       numeric(5,4),
  uncertainty_score  numeric(5,4),
  referral_flag      boolean NOT NULL DEFAULT false,
  reason_codes       text[] NOT NULL DEFAULT '{}',
  modality_mask      jsonb NOT NULL DEFAULT '{}',
  treatment_response response_category,
  raw_output         jsonb,
  inference_ms       int,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (visit_id, model_version_id),
  CHECK (NOT referral_flag OR risk_category IS NULL),
  CHECK (NOT is_baseline OR (risk_score IS NULL AND risk_category IS NULL))
);
CREATE INDEX ix_predictions_lesion ON predictions(lesion_id, created_at);

CREATE TABLE explanations (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  prediction_id          uuid UNIQUE NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
  attention_weights      jsonb NOT NULL DEFAULT '{}',
  difference_map_file_id uuid REFERENCES stored_files(id),
  saliency_file_id       uuid REFERENCES stored_files(id),
  change_summary         text[] NOT NULL DEFAULT '{}',
  registration_warning   boolean NOT NULL DEFAULT false,
  saliency_passed_check  boolean NOT NULL DEFAULT true
);

CREATE TABLE clinician_reviews (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  prediction_id  uuid NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
  reviewer_id    uuid NOT NULL REFERENCES users(id),
  decision       review_decision NOT NULL,
  final_category risk_category NOT NULL,
  reason         text,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_reviews_prediction ON clinician_reviews(prediction_id, created_at DESC);

CREATE TABLE reports (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_number         varchar(30) UNIQUE NOT NULL,
  patient_id            uuid NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  hospital_id           uuid NOT NULL REFERENCES hospitals(id),
  lesion_id             uuid REFERENCES lesions(id),
  prediction_id         uuid REFERENCES predictions(id),
  status                report_status NOT NULL DEFAULT 'draft',
  final_category        risk_category,
  patient_summary       text,
  doctor_notes          text,
  recommendation        text,
  pdf_file_id           uuid REFERENCES stored_files(id),
  clinician_pdf_file_id uuid REFERENCES stored_files(id),
  version               int NOT NULL DEFAULT 1,
  supersedes_id         uuid REFERENCES reports(id),
  created_by            uuid REFERENCES users(id),
  signed_by             uuid REFERENCES users(id),
  signed_at             timestamptz,
  released_at           timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  CHECK (status NOT IN ('signed','released') OR signed_by IS NOT NULL)
);
CREATE INDEX ix_reports_patient ON reports(patient_id, status);

CREATE TABLE audit_log (
  id           bigserial PRIMARY KEY,
  occurred_at  timestamptz NOT NULL DEFAULT now(),
  hospital_id  uuid,
  user_id      uuid,
  role         user_role,
  action       varchar(50) NOT NULL,
  entity_type  varchar(50),
  entity_id    uuid,
  ip           varchar(45),
  user_agent   text,
  details      jsonb NOT NULL DEFAULT '{}',
  prev_hash    char(64),
  row_hash     char(64)
);
CREATE INDEX ix_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX ix_audit_hospital_time ON audit_log(hospital_id, occurred_at DESC);

CREATE OR REPLACE FUNCTION audit_chain() RETURNS trigger AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(42);
  SELECT row_hash INTO NEW.prev_hash FROM audit_log ORDER BY id DESC LIMIT 1;
  NEW.row_hash := encode(digest(
      coalesce(NEW.prev_hash,'') || NEW.occurred_at::text || coalesce(NEW.user_id::text,'') ||
      NEW.action || coalesce(NEW.entity_id::text,'') || NEW.details::text, 'sha256'), 'hex');
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_audit_chain BEFORE INSERT ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_chain();

CREATE OR REPLACE FUNCTION audit_immutable() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_immutable();
