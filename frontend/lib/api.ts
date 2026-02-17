import type {
  SystemHealth,
  Job,
  Application,
  ScraperStatus,
  PaginatedResponse,
  SetupStatus,
  CompanySource,
} from "./types"

const BASE = "http://localhost:8000"

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${path}`)
  return res.json()
}

export const api = {
  getHealth: () => request<SystemHealth>("/api/health"),
  getJobs: (params?: { cursor?: number; limit?: number; site?: string; status?: string; cv_profile?: string }) => {
    const q = new URLSearchParams()
    if (params?.cursor) q.set("cursor", String(params.cursor))
    if (params?.limit) q.set("limit", String(params.limit))
    if (params?.site) q.set("site", params.site)
    if (params?.status) q.set("status", params.status)
    if (params?.cv_profile) q.set("cv_profile", params.cv_profile)
    return request<PaginatedResponse<Job>>(`/api/jobs?${q}`)
  },
  getJobCounts: () => request<Record<string, number>>("/api/jobs/counts"),
  getApplications: (params?: { cursor?: number; status?: string }) => {
    const q = new URLSearchParams()
    if (params?.cursor) q.set("cursor", String(params.cursor))
    if (params?.status) q.set("status", params.status)
    return request<PaginatedResponse<Application>>(`/api/applications?${q}`)
  },
  getApplicationCounts: () => request<Record<string, number>>("/api/applications/counts"),
  getPendingReviews: () => request<{ items: Application[]; count: number }>("/api/applications/pending-reviews"),
  authorizeApplication: (id: number) => request<{ status: string }>(`/api/applications/${id}/authorize`, { method: "POST" }),
  rejectApplication: (id: number) => request<{ status: string }>(`/api/applications/${id}/reject`, { method: "POST" }),
  getScraperStatus: () => request<{ scrapers: ScraperStatus[] }>("/api/scrapers/status"),
  triggerScraper: (site: string) => request<{ status: string; task_id: string }>(`/api/scrapers/${site}/trigger`, { method: "POST" }),
  generateCV: (applicationId: number) => request<{ status: string; task_id: string }>(`/api/cv/generate/${applicationId}`, { method: "POST" }),
  getSettings: () => request<Record<string, string>>("/api/settings"),
  updateSettings: (data: Record<string, string>) => request<{ status: string }>("/api/settings", { method: "POST", body: JSON.stringify(data) }),
  getCompanySources: () => request<{ items: CompanySource[] }>("/api/company-sources"),
  addCompanySource: (data: Partial<CompanySource>) => request<CompanySource>("/api/company-sources", { method: "POST", body: JSON.stringify(data) }),
  getSetupStatus: () => request<SetupStatus>("/api/setup/status"),
  acceptTos: () => request<{ accepted_at: string }>("/api/setup/accept-tos", { method: "POST" }),
  completeSetup: () => request<{ status: string }>("/api/setup/complete", { method: "POST" }),
}

export function createSSEConnection(
  onEvent: (event: string, data: unknown) => void
): () => void {
  const es = new EventSource(`${BASE}/api/events`)
  const handler = (e: MessageEvent) => {
    try { onEvent(e.type, JSON.parse(e.data)) } catch { onEvent(e.type, e.data) }
  }
  const events = [
    "scraper_finished",
    "scraper_error",
    "cv_generation_started",
    "cv_generation_complete",
    "review_ready",
    "application_submitted",
    "application_authorized",
    "application_rejected",
  ]
  events.forEach(evt => es.addEventListener(evt, handler as EventListener))
  return () => es.close()
}
