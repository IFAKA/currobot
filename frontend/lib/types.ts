export type ApplicationStatus =
  | "scraped" | "qualified" | "cv_generating" | "cv_ready"
  | "cv_failed_validation" | "cv_approved" | "application_started"
  | "form_filled" | "pending_human_review" | "submitted_ambiguous"
  | "applied" | "acknowledged" | "interview_scheduled" | "interviewed"
  | "offered" | "rejected" | "withdrawn" | "expired"

export interface Job {
  id: number; site: string; title: string; company: string; location: string | null;
  url: string; status: string; cv_profile: string | null; salary_raw: string | null;
  contract_type: string | null; posted_at: string | null; scraped_at: string;
}

export interface Application {
  id: number; job_id: number; status: ApplicationStatus; cv_profile: string;
  company: string; quality_score: number | null; authorized_by_human: boolean;
  authorized_at: string | null; form_screenshot_path: string | null;
  form_url: string | null; created_at: string; updated_at: string;
}

export interface ScraperStatus {
  site: string; last_run: string | null; last_status: string;
  jobs_found: number; jobs_new: number; consecutive_zero_runs: number;
  error_message: string | null;
}

export interface SystemHealth {
  status: string; setup_complete: boolean;
  ram_total_gb: number; ram_available_gb: number; ram_percent: number;
  disk_free_gb: number; ollama_host: string; timestamp: string;
}

export interface PaginatedResponse<T> {
  items: T[]; next_cursor: number | null;
}

export interface SetupStatus {
  system_check: boolean; ollama_running: boolean; model_downloaded: boolean;
  cv_uploaded: boolean; tos_accepted: boolean; setup_complete: boolean; ready: boolean;
}

export interface CompanySource {
  id: number; company_name: string; source_url: string;
  scraper_type: string; enabled: boolean; cv_profile: string;
}
