"""P5 monitoring: histopathology results on biopsies/excisions (ground truth for the fairness report) and audit
log search indexes.

Revision ID: 0004_monitoring
Revises: 0003_prediction_history
Create Date: 2026-10-31
"""
from alembic import op

revision = "0004_monitoring"
down_revision = "0003_prediction_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE treatment_events
            ADD COLUMN histopathology varchar(20)
                CONSTRAINT ck_treatment_histopathology CHECK (histopathology IN ('melanoma', 'not_melanoma')),
            ADD COLUMN histopathology_recorded_by uuid REFERENCES users(id),
            ADD COLUMN histopathology_recorded_at timestamptz;
        CREATE INDEX ix_treatment_histopathology ON treatment_events(lesion_id, treatment_date DESC)
            WHERE histopathology IS NOT NULL;
        CREATE INDEX ix_audit_time ON audit_log(occurred_at DESC);
        CREATE INDEX ix_audit_user_time ON audit_log(user_id, occurred_at DESC);
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP INDEX IF EXISTS ix_audit_user_time;
        DROP INDEX IF EXISTS ix_audit_time;
        DROP INDEX IF EXISTS ix_treatment_histopathology;
        ALTER TABLE treatment_events
            DROP COLUMN IF EXISTS histopathology_recorded_at,
            DROP COLUMN IF EXISTS histopathology_recorded_by,
            DROP COLUMN IF EXISTS histopathology;
        """
    )
