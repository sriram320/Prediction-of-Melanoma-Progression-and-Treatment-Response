"""Initial MelanoTrack schema (tables, enums, audit hash-chain triggers).

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-07
"""
from pathlib import Path

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0001_initial.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP TABLE IF EXISTS audit_log, reports, clinician_reviews, explanations, predictions,
            inference_jobs, model_versions, treatment_events, documents, images, visits, lesions,
            stored_files, patient_invites, patient_identity, patients, refresh_tokens, users, hospitals CASCADE;
        DROP FUNCTION IF EXISTS audit_chain, audit_immutable;
        DROP SEQUENCE IF EXISTS report_number_seq;
        DROP TYPE IF EXISTS user_role, image_modality, risk_category, job_status, report_status,
            response_category, review_decision, document_category, lesion_status, sex_type;
        """
    )
