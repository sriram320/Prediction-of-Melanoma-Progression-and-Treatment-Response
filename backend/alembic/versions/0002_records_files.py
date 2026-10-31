"""P2 records & files: keep original DICOM uploads, and index the file-access lookups.

Revision ID: 0002_records_files
Revises: 0001_initial
Create Date: 2026-10-24
"""
from alembic import op

revision = "0002_records_files"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE images ADD COLUMN source_file_id uuid REFERENCES stored_files(id);
        CREATE INDEX ix_images_file ON images(file_id);
        CREATE INDEX ix_documents_file ON documents(file_id);
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP INDEX IF EXISTS ix_documents_file;
        DROP INDEX IF EXISTS ix_images_file;
        ALTER TABLE images DROP COLUMN IF EXISTS source_file_id;
        """
    )
