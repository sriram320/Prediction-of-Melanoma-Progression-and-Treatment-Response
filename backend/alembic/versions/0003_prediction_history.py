"""P3 inference: keep every prediction (re-running an analysis adds a result instead of replacing one).

Revision ID: 0003_prediction_history
Revises: 0002_records_files
Create Date: 2026-10-31
"""
from alembic import op

revision = "0003_prediction_history"
down_revision = "0002_records_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE predictions DROP CONSTRAINT IF EXISTS predictions_visit_id_model_version_id_key;
        CREATE INDEX ix_predictions_visit ON predictions(visit_id, created_at DESC);
        CREATE INDEX ix_jobs_lesion ON inference_jobs(lesion_id, created_at DESC);
        CREATE UNIQUE INDEX ux_jobs_one_active ON inference_jobs(lesion_id) WHERE status IN ('queued', 'running');
        CREATE INDEX ix_images_mask ON images(mask_file_id) WHERE mask_file_id IS NOT NULL;
        CREATE INDEX ix_explanations_files ON explanations(difference_map_file_id, saliency_file_id);
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP INDEX IF EXISTS ix_explanations_files;
        DROP INDEX IF EXISTS ix_images_mask;
        DROP INDEX IF EXISTS ux_jobs_one_active;
        DROP INDEX IF EXISTS ix_jobs_lesion;
        DROP INDEX IF EXISTS ix_predictions_visit;
        ALTER TABLE predictions ADD CONSTRAINT predictions_visit_id_model_version_id_key
            UNIQUE (visit_id, model_version_id);
        """
    )
