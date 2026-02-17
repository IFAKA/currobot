"""SQLAlchemy ORM models + status enums + state machine."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON,
    String, Text, UniqueConstraint, event, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class JobStatus(str, enum.Enum):
    scraped  = "scraped"
    qualified = "qualified"
    skipped  = "skipped"
    expired  = "expired"


class ApplicationStatus(str, enum.Enum):
    scraped               = "scraped"
    qualified             = "qualified"
    cv_generating         = "cv_generating"
    cv_ready              = "cv_ready"
    cv_failed_validation  = "cv_failed_validation"
    cv_approved           = "cv_approved"
    application_started   = "application_started"
    form_filled           = "form_filled"
    pending_human_review  = "pending_human_review"
    submitted_ambiguous   = "submitted_ambiguous"
    applied               = "applied"
    acknowledged          = "acknowledged"
    interview_scheduled   = "interview_scheduled"
    interviewed           = "interviewed"
    offered               = "offered"
    rejected              = "rejected"
    withdrawn             = "withdrawn"
    expired               = "expired"


class CVProfile(str, enum.Enum):
    cashier      = "cashier"
    stocker      = "stocker"
    logistics    = "logistics"
    frontend_dev = "frontend_dev"
    fullstack_dev = "fullstack_dev"


class ScraperRunStatus(str, enum.Enum):
    running   = "running"
    completed = "completed"
    failed    = "failed"
    disabled  = "disabled"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("site", "external_id", name="uq_job_site_external_id"),
        Index("ix_jobs_site", "site"),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_scraped_at", "scraped_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)  # SHA256 synthetic or platform ID
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(256), nullable=False)
    location: Mapped[str] = mapped_column(String(256), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    salary_raw: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    contract_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.scraped.value, nullable=False)
    cv_profile: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    applications: Mapped[list["Application"]] = relationship(back_populates="job")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_status", "status"),
        Index("ix_applications_job_id", "job_id"),
        Index("ix_applications_company", "company"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(64), default=ApplicationStatus.scraped.value, nullable=False
    )
    cv_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    company: Mapped[str] = mapped_column(String(256), nullable=False)

    # CV / documents
    cv_canonical_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    cv_adapted_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    cv_pdf_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_letter_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_rubric: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Form state (serialized before human review)
    form_screenshot_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    form_fields_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    form_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Confirmation
    confirmation_screenshot_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmation_signal: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Authorization audit trail
    authorized_by_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    authorized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="applications")
    events: Mapped[list["ApplicationEvent"]] = relationship(back_populates="application")


class ApplicationEvent(Base):
    """Immutable audit log of every status transition."""
    __tablename__ = "application_events"
    __table_args__ = (
        Index("ix_events_application_id", "application_id"),
        Index("ix_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False)
    old_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    new_status: Mapped[str] = mapped_column(String(64), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(128), nullable=False)  # "scraper", "cv_adapter", "human", etc.
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    application: Mapped["Application"] = relationship(back_populates="events")


class CompanyBlocklist(Base):
    __tablename__ = "company_blocklist"
    __table_args__ = (
        UniqueConstraint("company_name", name="uq_blocklist_company"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class CompanyApplicationRule(Base):
    """Rate limit per company: max N applications per M days."""
    __tablename__ = "company_application_rules"
    __table_args__ = (
        UniqueConstraint("company_name", name="uq_rules_company"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    max_per_period: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    period_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class CompanySource(Base):
    """Configurable career page URLs for generic scraper."""
    __tablename__ = "company_sources"
    __table_args__ = (
        UniqueConstraint("company_name", "source_url", name="uq_source_company_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    scraper_type: Mapped[str] = mapped_column(String(64), nullable=False)  # "career_page", "greenhouse", "lever", etc.
    css_selector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # for career_page type
    extra_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cv_profile: Mapped[str] = mapped_column(String(32), default="fullstack_dev", nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class ScraperRun(Base):
    __tablename__ = "scraper_runs"
    __table_args__ = (
        Index("ix_scraper_runs_site", "site"),
        Index("ix_scraper_runs_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checkpoint_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    structure_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    consecutive_zero_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Settings(Base):
    """Key-value settings store for runtime config."""
    __tablename__ = "settings"
    __table_args__ = (
        UniqueConstraint("key", name="uq_settings_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class CVDocument(Base):
    """Tracks generated CV files per application."""
    __tablename__ = "cv_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False)
    cv_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    pdf_path: Mapped[str] = mapped_column(Text, nullable=False)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    validation_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
