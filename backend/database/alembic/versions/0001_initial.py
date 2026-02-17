"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("site", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(256), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("company", sa.String(256), nullable=False),
        sa.Column("location", sa.String(256), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("salary_raw", sa.String(256), nullable=True),
        sa.Column("contract_type", sa.String(128), nullable=True),
        sa.Column("posted_at", sa.DateTime, nullable=True),
        sa.Column("scraped_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(32), server_default="scraped", nullable=False),
        sa.Column("cv_profile", sa.String(32), nullable=True),
        sa.Column("raw_data", sa.JSON, nullable=True),
        sa.UniqueConstraint("site", "external_id", name="uq_job_site_external_id"),
    )
    op.create_index("ix_jobs_site", "jobs", ["site"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_scraped_at", "jobs", ["scraped_at"])

    op.create_table(
        "applications",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("status", sa.String(64), server_default="scraped", nullable=False),
        sa.Column("cv_profile", sa.String(32), nullable=False),
        sa.Column("company", sa.String(256), nullable=False),
        sa.Column("cv_canonical_json", sa.JSON, nullable=True),
        sa.Column("cv_adapted_json", sa.JSON, nullable=True),
        sa.Column("cv_pdf_path", sa.Text, nullable=True),
        sa.Column("cover_letter_text", sa.Text, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("quality_rubric", sa.JSON, nullable=True),
        sa.Column("form_screenshot_path", sa.Text, nullable=True),
        sa.Column("form_fields_json", sa.JSON, nullable=True),
        sa.Column("form_url", sa.Text, nullable=True),
        sa.Column("confirmation_screenshot_path", sa.Text, nullable=True),
        sa.Column("confirmation_signal", sa.String(64), nullable=True),
        sa.Column("authorized_by_human", sa.Boolean, server_default="0", nullable=False),
        sa.Column("authorized_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_applications_status", "applications", ["status"])
    op.create_index("ix_applications_job_id", "applications", ["job_id"])
    op.create_index("ix_applications_company", "applications", ["company"])

    op.create_table(
        "application_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("old_status", sa.String(64), nullable=True),
        sa.Column("new_status", sa.String(64), nullable=False),
        sa.Column("triggered_by", sa.String(128), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_events_application_id", "application_events", ["application_id"])
    op.create_index("ix_events_created_at", "application_events", ["created_at"])

    op.create_table(
        "company_blocklist",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_name", sa.String(256), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("added_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_name", name="uq_blocklist_company"),
    )

    op.create_table(
        "company_application_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_name", sa.String(256), nullable=False),
        sa.Column("max_per_period", sa.Integer, server_default="2", nullable=False),
        sa.Column("period_days", sa.Integer, server_default="14", nullable=False),
        sa.Column("added_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_name", name="uq_rules_company"),
    )

    op.create_table(
        "company_sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_name", sa.String(256), nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("scraper_type", sa.String(64), nullable=False),
        sa.Column("css_selector", sa.Text, nullable=True),
        sa.Column("extra_config", sa.JSON, nullable=True),
        sa.Column("enabled", sa.Boolean, server_default="1", nullable=False),
        sa.Column("cv_profile", sa.String(32), server_default="fullstack_dev", nullable=False),
        sa.Column("added_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_name", "source_url", name="uq_source_company_url"),
    )

    op.create_table(
        "scraper_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("site", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("jobs_found", sa.Integer, server_default="0", nullable=False),
        sa.Column("jobs_new", sa.Integer, server_default="0", nullable=False),
        sa.Column("checkpoint_json", sa.JSON, nullable=True),
        sa.Column("structure_hash", sa.String(64), nullable=True),
        sa.Column("consecutive_zero_runs", sa.Integer, server_default="0", nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("ix_scraper_runs_site", "scraper_runs", ["site"])
    op.create_index("ix_scraper_runs_started_at", "scraper_runs", ["started_at"])

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("value", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("key", name="uq_settings_key"),
    )

    op.create_table(
        "cv_documents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("cv_profile", sa.String(32), nullable=False),
        sa.Column("pdf_path", sa.Text, nullable=False),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("validation_passed", sa.Boolean, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cv_documents")
    op.drop_table("settings")
    op.drop_table("scraper_runs")
    op.drop_table("company_sources")
    op.drop_table("company_application_rules")
    op.drop_table("company_blocklist")
    op.drop_table("application_events")
    op.drop_table("applications")
    op.drop_table("jobs")
