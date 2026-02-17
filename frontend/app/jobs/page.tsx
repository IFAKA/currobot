"use client"
import { useEffect, useState, useCallback, useRef } from "react"
import { motion, AnimatePresence } from "motion/react"
import {
  Search, MapPin, DollarSign, ExternalLink, Briefcase,
  ChevronDown, Filter
} from "lucide-react"
import { api } from "@/lib/api"
import type { Job } from "@/lib/types"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { StatusBadge, ProfilePill } from "@/components/ui/badge"
import { formatDate, cvProfileColor, cn } from "@/lib/utils"
import { useRouter } from "next/navigation"

const SITES = ["", "infojobs", "linkedin", "indeed", "trabajos", "jobtoday"]
const STATUSES = ["", "scraped", "qualified", "cv_generating", "cv_ready", "applied", "rejected"]
const PROFILES = ["", "cashier", "stocker", "logistics", "frontend_dev", "fullstack_dev"]

function JobSkeleton() {
  return (
    <div className="animate-pulse bg-white/5 border border-white/10 rounded-2xl p-4 space-y-3">
      <div className="flex justify-between items-start">
        <div className="space-y-2 flex-1">
          <div className="h-5 bg-white/10 rounded w-48" />
          <div className="h-3.5 bg-white/5 rounded w-32" />
          <div className="h-3 bg-white/5 rounded w-40" />
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="h-6 bg-white/10 rounded-full w-20" />
          <div className="h-5 bg-white/5 rounded-full w-16" />
        </div>
      </div>
    </div>
  )
}

function JobRow({
  job,
  focused,
  onFocus,
}: {
  job: Job
  focused: boolean
  onFocus: () => void
}) {
  const router = useRouter()
  const profileColorClass = job.cv_profile ? cvProfileColor(job.cv_profile) : "bg-white/5 text-[#8E8E93]"

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ type: "spring", stiffness: 200, damping: 22 }}
    >
      <Card
        className={cn(
          "transition-all duration-150",
          focused && "ring-2 ring-[#007AFF] ring-offset-2 ring-offset-[#1C1C1E]"
        )}
        onClick={onFocus}
      >
        <div className="flex items-start gap-4">
          {/* LEFT: cv_profile chip, company, title, location */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              {job.cv_profile && (
                <span className={cn(
                  "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
                  profileColorClass
                )}>
                  {job.cv_profile.replace(/_/g, " ")}
                </span>
              )}
            </div>
            <p className="text-sm font-bold text-white">{job.company}</p>
            <p className="text-xs text-white/70 mt-0.5">{job.title}</p>
            {job.location && (
              <div className="flex items-center gap-1 mt-1">
                <MapPin className="h-3 w-3 text-[#8E8E93]" />
                <span className="text-xs text-[#8E8E93]">{job.location}</span>
              </div>
            )}
          </div>

          {/* MIDDLE: site, posted_at */}
          <div className="hidden sm:flex flex-col items-center gap-1 shrink-0 text-center min-w-[80px]">
            <span className="text-xs text-[#8E8E93] font-medium">{job.site}</span>
            <span className="text-[11px] text-[#8E8E93]">{formatDate(job.posted_at ?? job.scraped_at)}</span>
          </div>

          {/* RIGHT: StatusBadge, salary_raw, Apply button */}
          <div className="flex flex-col items-end gap-2 shrink-0">
            <StatusBadge status={job.status} />
            {job.salary_raw && (
              <span className="flex items-center gap-1 text-xs text-[#8E8E93]">
                <DollarSign className="h-3 w-3" />
                {job.salary_raw}
              </span>
            )}
            {job.cv_profile && <ProfilePill profile={job.cv_profile} />}
          </div>
        </div>

        <AnimatePresence>
          {focused && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 28 }}
              className="overflow-hidden"
            >
              <div className="flex items-center gap-2 mt-3 pt-3 border-t border-white/5">
                <a
                  href={job.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={e => e.stopPropagation()}
                >
                  <Button size="sm" variant="outline">
                    <ExternalLink className="h-3 w-3" />
                    View listing
                  </Button>
                </a>
                <Button
                  size="sm"
                  onClick={e => {
                    e.stopPropagation()
                    router.push(`/review?id=${job.id}`)
                  }}
                >
                  <Briefcase className="h-3 w-3" />
                  Apply
                </Button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>
    </motion.div>
  )
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [cursor, setCursor] = useState<number | undefined>(undefined)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [focusedIndex, setFocusedIndex] = useState(0)
  const [totalCount, setTotalCount] = useState(0)

  const [filters, setFilters] = useState({
    site: "",
    status: "",
    cv_profile: "",
    search: "",
  })

  const filterRef = useRef(filters)
  filterRef.current = filters

  const fetchJobs = useCallback(async (reset = false) => {
    if (reset) setLoading(true)
    try {
      const f = filterRef.current
      const res = await api.getJobs({
        site: f.site || undefined,
        status: f.status || undefined,
        cv_profile: f.cv_profile || undefined,
        limit: 20,
      })
      if (reset) {
        setJobs(res.items)
      } else {
        setJobs(prev => [...prev, ...res.items])
      }
      setHasMore(res.next_cursor !== null)
      setCursor(res.next_cursor ?? undefined)
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [])

  useEffect(() => {
    fetchJobs(true)
  }, [filters, fetchJobs])

  const loadMore = async () => {
    if (!hasMore || loadingMore) return
    setLoadingMore(true)
    try {
      const f = filterRef.current
      const res = await api.getJobs({
        cursor,
        site: f.site || undefined,
        status: f.status || undefined,
        cv_profile: f.cv_profile || undefined,
        limit: 20,
      })
      setJobs(prev => [...prev, ...res.items])
      setHasMore(res.next_cursor !== null)
      setCursor(res.next_cursor ?? undefined)
    } finally {
      setLoadingMore(false)
    }
  }

  // Fetch total count
  useEffect(() => {
    api.getJobCounts().then(c => {
      setTotalCount(Object.values(c).reduce((a, b) => a + b, 0))
    }).catch(() => {})
  }, [])

  // J/K keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return
      if (e.key === "j") setFocusedIndex(i => Math.min(i + 1, filteredJobs.length - 1))
      if (e.key === "k") setFocusedIndex(i => Math.max(i - 1, 0))
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [jobs.length])

  const filteredJobs = filters.search
    ? jobs.filter(j =>
        j.title.toLowerCase().includes(filters.search.toLowerCase()) ||
        j.company.toLowerCase().includes(filters.search.toLowerCase())
      )
    : jobs

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Jobs</h1>
          <p className="text-sm text-[#8E8E93] mt-0.5">{totalCount} total scraped</p>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="bg-white/5 border border-white/10 rounded-2xl p-3 flex flex-wrap gap-2 items-center">
        <Filter className="h-4 w-4 text-[#8E8E93] shrink-0" />

        {/* Search */}
        <div className="flex items-center gap-1.5 flex-1 min-w-48 bg-white/5 rounded-xl px-3 py-1.5">
          <Search className="h-3.5 w-3.5 text-[#8E8E93]" />
          <input
            type="text"
            placeholder="Search title or company..."
            value={filters.search}
            onChange={e => setFilters(f => ({ ...f, search: e.target.value }))}
            className="flex-1 bg-transparent text-sm text-white placeholder:text-[#8E8E93] outline-none"
          />
        </div>

        {/* Site dropdown */}
        <div className="relative">
          <select
            value={filters.site}
            onChange={e => setFilters(f => ({ ...f, site: e.target.value }))}
            className="appearance-none bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 pr-7 text-sm text-white outline-none cursor-pointer"
          >
            <option value="">All sites</option>
            {SITES.filter(s => s).map(s => (
              <option key={s} value={s} className="bg-[#2C2C2E]">{s}</option>
            ))}
          </select>
          <ChevronDown className="h-3 w-3 text-[#8E8E93] absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>

        {/* Profile dropdown */}
        <div className="relative">
          <select
            value={filters.cv_profile}
            onChange={e => setFilters(f => ({ ...f, cv_profile: e.target.value }))}
            className="appearance-none bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 pr-7 text-sm text-white outline-none cursor-pointer"
          >
            <option value="">All profiles</option>
            {PROFILES.filter(p => p).map(p => (
              <option key={p} value={p} className="bg-[#2C2C2E]">{p.replace(/_/g, " ")}</option>
            ))}
          </select>
          <ChevronDown className="h-3 w-3 text-[#8E8E93] absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>

        {/* Status dropdown */}
        <div className="relative">
          <select
            value={filters.status}
            onChange={e => setFilters(f => ({ ...f, status: e.target.value }))}
            className="appearance-none bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 pr-7 text-sm text-white outline-none cursor-pointer"
          >
            <option value="">All statuses</option>
            {STATUSES.filter(s => s).map(s => (
              <option key={s} value={s} className="bg-[#2C2C2E]">{s.replace(/_/g, " ")}</option>
            ))}
          </select>
          <ChevronDown className="h-3 w-3 text-[#8E8E93] absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
      </div>

      <p className="text-xs text-[#8E8E93] px-1">
        J / K to navigate · Enter to expand · {filteredJobs.length} results shown
      </p>

      {/* Job List */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => <JobSkeleton key={i} />)}
        </div>
      ) : filteredJobs.length === 0 ? (
        <div className="text-center py-20">
          <Briefcase className="h-10 w-10 text-[#8E8E93] mx-auto mb-3" />
          <p className="text-[#8E8E93]">No jobs found.</p>
          <p className="text-xs text-[#8E8E93] mt-1">
            Trigger a scrape from the dashboard to populate jobs.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <AnimatePresence mode="popLayout">
            {filteredJobs.map((job, i) => (
              <JobRow
                key={job.id}
                job={job}
                focused={focusedIndex === i}
                onFocus={() => setFocusedIndex(i)}
              />
            ))}
          </AnimatePresence>
        </div>
      )}

      {/* Load More */}
      {hasMore && !loading && (
        <div className="flex justify-center pt-2">
          <Button
            variant="outline"
            loading={loadingMore}
            onClick={loadMore}
          >
            <ChevronDown className="h-4 w-4" />
            Load more jobs
          </Button>
        </div>
      )}
    </div>
  )
}
