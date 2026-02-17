"use client"
import { useEffect, useState, useCallback } from "react"
import { motion } from "motion/react"
import {
  Cpu, Zap, AlertTriangle, CheckCircle2, RefreshCw,
  TrendingUp, Clock
} from "lucide-react"
import { api, createSSEConnection } from "@/lib/api"
import type { SystemHealth, ScraperStatus, Application } from "@/lib/types"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { HealthDot } from "@/components/ui/health-dot"
import { formatDate } from "@/lib/utils"
import Link from "next/link"

function SkeletonBlock({ className }: { className?: string }) {
  return (
    <div className={`animate-pulse bg-white/5 rounded-xl ${className ?? ""}`} />
  )
}

function RAMBar({ used, total, percent }: { used: number; total: number; percent: number }) {
  const color = percent > 85 ? "bg-[#FF3B30]" : percent > 60 ? "bg-amber-400" : "bg-[#34C759]"
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-[#8E8E93]">
        <span>RAM</span>
        <span>{used.toFixed(1)} / {total.toFixed(1)} GB ({percent.toFixed(0)}%)</span>
      </div>
      <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
        <motion.div
          className={`h-full rounded-full ${color}`}
          initial={{ width: 0 }}
          animate={{ width: `${percent}%` }}
          transition={{ type: "spring", stiffness: 100, damping: 20 }}
        />
      </div>
    </div>
  )
}

function DiskBar({ freeGb }: { freeGb: number }) {
  const warningLevel = freeGb < 5 ? "bg-[#FF3B30]" : freeGb < 20 ? "bg-amber-400" : "bg-[#34C759]"
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-[#8E8E93]">
        <span>Disk Free</span>
        <span>{freeGb.toFixed(1)} GB</span>
      </div>
      <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
        <motion.div
          className={`h-full rounded-full ${warningLevel}`}
          style={{ width: `${Math.min(100, (freeGb / 100) * 100)}%` }}
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(100, (freeGb / 100) * 100)}%` }}
          transition={{ type: "spring", stiffness: 100, damping: 20 }}
        />
      </div>
    </div>
  )
}

function FunnelBar({ counts }: { counts: Record<string, number> }) {
  const stages = [
    { key: "scraped", label: "Scraped", color: "bg-[#8E8E93]" },
    { key: "qualified", label: "Qualified", color: "bg-[#007AFF]" },
    { key: "cv_ready", label: "CV Ready", color: "bg-purple-400" },
    { key: "applied", label: "Applied", color: "bg-[#34C759]" },
    { key: "offered", label: "Offered", color: "bg-amber-400" },
  ]
  const max = Math.max(...stages.map(s => counts[s.key] ?? 0), 1)

  return (
    <div className="space-y-2">
      {stages.map(stage => {
        const val = counts[stage.key] ?? 0
        const pct = (val / max) * 100
        return (
          <div key={stage.key} className="flex items-center gap-3">
            <span className="text-xs text-[#8E8E93] w-20 text-right shrink-0">{stage.label}</span>
            <div className="flex-1 h-5 bg-white/5 rounded-lg overflow-hidden relative">
              <motion.div
                className={`h-full rounded-lg ${stage.color} opacity-80`}
                initial={{ width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{ type: "spring", stiffness: 80, damping: 20, delay: 0.1 }}
              />
              <span className="absolute inset-0 flex items-center px-2 text-xs font-medium text-white">
                {val}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ScraperCard({
  scraper,
  onTrigger,
}: {
  scraper: ScraperStatus
  onTrigger: (site: string) => void
}) {
  const [triggering, setTriggering] = useState(false)

  const dotStatus =
    scraper.last_status === "ok" || scraper.last_status === "success"
      ? "ok"
      : scraper.last_status === "running"
        ? "running"
        : scraper.last_status === "error"
          ? "error"
          : "unknown"

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      await onTrigger(scraper.site)
    } finally {
      setTimeout(() => setTriggering(false), 2000)
    }
  }

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <HealthDot status={dotStatus} pulse={dotStatus === "running"} />
          <span className="text-sm font-semibold text-white capitalize">{scraper.site}</span>
        </div>
        <Button
          size="sm"
          variant="ghost"
          loading={triggering}
          onClick={handleTrigger}
          className="text-[#8E8E93]"
        >
          <Zap className="h-3 w-3" />
          Run
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-[#8E8E93]">Last run</p>
          <p className="text-white">{formatDate(scraper.last_run)}</p>
        </div>
        <div>
          <p className="text-[#8E8E93]">Jobs found</p>
          <p className="text-white">
            {scraper.jobs_found} <span className="text-[#34C759]">(+{scraper.jobs_new} new)</span>
          </p>
        </div>
      </div>

      {scraper.error_message && (
        <p className="text-xs text-[#FF3B30] bg-[#FF3B30]/10 rounded-lg px-2 py-1.5 truncate">
          {scraper.error_message}
        </p>
      )}

      {scraper.consecutive_zero_runs > 2 && (
        <p className="text-xs text-amber-400">
          {scraper.consecutive_zero_runs} consecutive zero-result runs
        </p>
      )}
    </Card>
  )
}

export default function DashboardPage() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [scrapers, setScrapers] = useState<ScraperStatus[]>([])
  const [appCounts, setAppCounts] = useState<Record<string, number>>({})
  const [pendingReviews, setPendingReviews] = useState<Application[]>([])
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date())

  const fetchAll = useCallback(async () => {
    try {
      const [h, s, ac, pr] = await Promise.allSettled([
        api.getHealth(),
        api.getScraperStatus(),
        api.getApplicationCounts(),
        api.getPendingReviews(),
      ])
      if (h.status === "fulfilled") setHealth(h.value)
      if (s.status === "fulfilled") setScrapers(s.value.scrapers)
      if (ac.status === "fulfilled") setAppCounts(ac.value)
      if (pr.status === "fulfilled") setPendingReviews(pr.value.items)
      setLastRefresh(new Date())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 30000)
    const closeSSE = createSSEConnection((event) => {
      if (
        event === "scraper_finished" ||
        event === "scraper_error" ||
        event === "application_submitted" ||
        event === "review_ready"
      ) {
        fetchAll()
      }
    })
    return () => {
      clearInterval(interval)
      closeSSE()
    }
  }, [fetchAll])

  const handleTrigger = async (site: string) => {
    await api.triggerScraper(site)
  }

  const ollamaStatus = health
    ? health.status === "ok" || health.ollama_host ? "ok" : "error"
    : "unknown"

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-[#8E8E93] mt-0.5">
            JobBot — local automation
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-[#8E8E93]">
            <Clock className="h-3 w-3 inline mr-1" />
            Updated {formatDate(lastRefresh.toISOString())}
          </span>
          <Button size="sm" variant="ghost" onClick={fetchAll}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Pending Reviews Alert */}
      {pendingReviews.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
          className="bg-amber-400/10 border border-amber-400/20 rounded-2xl p-4 flex items-center justify-between"
        >
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-400 shrink-0" />
            <div>
              <p className="text-sm font-semibold text-amber-400">
                {pendingReviews.length} application{pendingReviews.length > 1 ? "s" : ""} pending human review
              </p>
              <p className="text-xs text-amber-400/70 mt-0.5">
                Review and authorize before the session expires
              </p>
            </div>
          </div>
          <Link href="/applications?status=pending_human_review">
            <Button size="sm" className="bg-amber-400 hover:bg-amber-500 text-black font-semibold">
              Review now
            </Button>
          </Link>
        </motion.div>
      )}

      {/* System Health Row */}
      <Card className="space-y-4">
        <CardHeader className="mb-0">
          <div className="flex items-center justify-between">
            <CardTitle>System Health</CardTitle>
            <div className="flex items-center gap-2">
              <HealthDot
                status={health ? (health.status === "ok" ? "ok" : "warning") : "unknown"}
                pulse={!health}
              />
              <span className="text-xs text-[#8E8E93]">
                {health ? health.status : "Checking..."}
              </span>
            </div>
          </div>
        </CardHeader>

        {loading ? (
          <div className="space-y-3">
            <SkeletonBlock className="h-4" />
            <SkeletonBlock className="h-4" />
          </div>
        ) : health ? (
          <div className="space-y-3">
            <RAMBar
              used={health.ram_total_gb - health.ram_available_gb}
              total={health.ram_total_gb}
              percent={health.ram_percent}
            />
            <DiskBar freeGb={health.disk_free_gb} />

            <div className="flex items-center gap-2 pt-1">
              <Cpu className="h-3.5 w-3.5 text-[#8E8E93]" />
              <span className="text-xs text-[#8E8E93]">Ollama:</span>
              <HealthDot status={ollamaStatus as "ok" | "error"} />
              <span className="text-xs text-white">{health.ollama_host}</span>
            </div>
          </div>
        ) : (
          <p className="text-sm text-[#FF3B30]">Backend unreachable — is the API running?</p>
        )}
      </Card>

      {/* Scrapers Grid */}
      <div>
        <h2 className="text-base font-semibold text-white mb-3 flex items-center gap-2">
          <Zap className="h-4 w-4 text-[#007AFF]" />
          Scrapers
        </h2>
        {loading ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <SkeletonBlock key={i} className="h-28" />
            ))}
          </div>
        ) : scrapers.length === 0 ? (
          <Card className="text-center py-8">
            <p className="text-[#8E8E93] text-sm">No scrapers configured yet.</p>
          </Card>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {scrapers.map((s, i) => (
              <motion.div
                key={s.site}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05, type: "spring", stiffness: 200, damping: 20 }}
              >
                <ScraperCard scraper={s} onTrigger={handleTrigger} />
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {/* Application Funnel */}
      <div>
        <h2 className="text-base font-semibold text-white mb-3 flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-[#34C759]" />
          Application Funnel
        </h2>
        <Card>
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <SkeletonBlock key={i} className="h-5" />
              ))}
            </div>
          ) : (
            <FunnelBar counts={appCounts} />
          )}
        </Card>
      </div>

      {/* Quick Stats */}
      {!loading && Object.keys(appCounts).length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "Total Jobs", value: Object.values(appCounts).reduce((a, b) => a + b, 0), color: "text-white" },
            { label: "Applied", value: appCounts.applied ?? 0, color: "text-[#34C759]" },
            { label: "Pending Review", value: appCounts.pending_human_review ?? 0, color: "text-amber-400" },
            { label: "Offered", value: appCounts.offered ?? 0, color: "text-purple-400" },
          ].map((stat, i) => (
            <motion.div
              key={stat.label}
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.05 + 0.1, type: "spring", stiffness: 200 }}
            >
              <Card className="text-center py-3">
                <p className={`text-2xl font-bold ${stat.color}`}>{stat.value}</p>
                <p className="text-xs text-[#8E8E93] mt-0.5">{stat.label}</p>
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      {/* Setup Incomplete Warning */}
      {health && !health.setup_complete && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-[#007AFF]/10 border border-[#007AFF]/20 rounded-2xl p-4 flex items-center justify-between"
        >
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-[#007AFF]" />
            <div>
              <p className="text-sm font-semibold text-[#007AFF]">Setup not complete</p>
              <p className="text-xs text-[#007AFF]/70">Complete the setup wizard to start automating</p>
            </div>
          </div>
          <Link href="/setup">
            <Button size="sm">Complete Setup</Button>
          </Link>
        </motion.div>
      )}
    </div>
  )
}
