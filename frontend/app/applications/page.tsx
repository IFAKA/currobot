"use client"
import { useEffect, useState, useCallback } from "react"
import { motion, AnimatePresence } from "motion/react"
import { useRouter } from "next/navigation"
import { XCircle, Clock } from "lucide-react"
import { api, createSSEConnection } from "@/lib/api"
import type { Application } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { formatDate, cvProfileColor, cn } from "@/lib/utils"
import { toast } from "@/lib/toast"

const COLUMNS: { status: string; label: string; accent: string }[] = [
  { status: "pending_human_review", label: "Pending Review",  accent: "border-amber-400/40" },
  { status: "cv_generating",        label: "CV Generating",   accent: "border-[#007AFF]/40" },
  { status: "applied",              label: "Applied",         accent: "border-[#34C759]/40" },
  { status: "offered",              label: "Offered",         accent: "border-[#34C759]/40" },
  { status: "rejected",             label: "Rejected",        accent: "border-[#FF3B30]/40" },
]

function QualityBadge({ score }: { score: number | null }) {
  if (score === null) return null
  const color =
    score >= 8 ? "text-[#34C759] bg-[#34C759]/10" :
    score >= 5 ? "text-amber-400 bg-amber-400/10" :
    "text-[#FF3B30] bg-[#FF3B30]/10"
  return (
    <span className={cn("text-xs font-semibold px-1.5 py-0.5 rounded-full", color)}>
      {"\u2B50"} {score}/10
    </span>
  )
}

function AppCard({
  app,
  onReject,
  onClick,
}: {
  app: Application
  onReject?: () => void
  onClick: () => void
}) {
  const isPending = app.status === "pending_human_review"

  return (
    <motion.div
      layout
      layoutId={`app-${app.id}`}
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.94 }}
      transition={{ type: "spring", stiffness: 260, damping: 24 }}
      whileHover={{ y: -1 }}
      className={cn(
        "bg-white/5 border border-white/10 rounded-xl p-3 cursor-pointer select-none",
        "hover:bg-white/[0.08] hover:border-white/20 transition-colors",
        isPending && "border-amber-400/30 bg-amber-400/5"
      )}
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-white truncate">{app.company}</p>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <span className={cn(
              "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
              cvProfileColor(app.cv_profile)
            )}>
              {app.cv_profile.replace(/_/g, " ")}
            </span>
            <QualityBadge score={app.quality_score} />
          </div>
        </div>
        <div className="text-right shrink-0">
          <span className="text-[11px] text-[#8E8E93]">{formatDate(app.updated_at)}</span>
        </div>
      </div>

      {isPending && (
        <div className="flex gap-1.5 mt-2.5 pt-2.5 border-t border-white/5">
          {onReject && (
            <Button
              size="sm"
              variant="destructive"
              className="flex-1 text-xs"
              onClick={e => { e.stopPropagation(); onReject() }}
            >
              <XCircle className="h-3 w-3" />
              Reject
            </Button>
          )}
          <Button
            size="sm"
            className="flex-1 text-xs"
            onClick={e => { e.stopPropagation(); onClick() }}
          >
            Review &rarr;
          </Button>
        </div>
      )}

      {app.authorized_at && (
        <div className="flex items-center gap-1 mt-2 text-[11px] text-[#8E8E93]">
          <Clock className="h-3 w-3" />
          Authorized {formatDate(app.authorized_at)}
        </div>
      )}
    </motion.div>
  )
}

function KanbanColumn({
  status,
  label,
  accent,
  apps,
  onReject,
  onCardClick,
}: {
  status: string
  label: string
  accent: string
  apps: Application[]
  onReject: (id: number) => void
  onCardClick: (app: Application) => void
}) {
  return (
    <div
      className={cn(
        "flex flex-col min-w-[240px] max-w-[300px] flex-shrink-0",
        "bg-white/[0.03] border rounded-2xl overflow-hidden",
        accent
      )}
    >
      {/* Column Header */}
      <div className="px-3 py-2.5 border-b border-white/5 flex items-center justify-between">
        <span className="text-xs font-semibold text-white">{label}</span>
        <span className="text-xs text-[#8E8E93] bg-white/5 px-1.5 py-0.5 rounded-full">
          {apps.length}
        </span>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2 max-h-[calc(100vh-220px)]">
        {apps.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <p className="text-xs text-[#8E8E93]">Empty</p>
          </div>
        ) : (
          <AnimatePresence>
            {apps.map(app => (
              <AppCard
                key={app.id}
                app={app}
                onReject={status === "pending_human_review" ? () => onReject(app.id) : undefined}
                onClick={() => onCardClick(app)}
              />
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  )
}

export default function ApplicationsPage() {
  const [applications, setApplications] = useState<Application[]>([])
  const [loading, setLoading] = useState(true)
  const [actionInProgress, setActionInProgress] = useState<number | null>(null)
  const router = useRouter()

  const fetchApplications = useCallback(async () => {
    try {
      const results: Application[] = []
      const statuses = COLUMNS.map(c => c.status)
      const fetches = statuses.map(s =>
        api.getApplications({ status: s }).catch(() => ({ items: [], next_cursor: null }))
      )
      const responses = await Promise.all(fetches)
      responses.forEach(r => results.push(...r.items))
      setApplications(results)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchApplications()
    // SSE: listen for review_ready events to refresh
    const closeSSE = createSSEConnection((event) => {
      if (
        event === "review_ready" ||
        event === "application_authorized" ||
        event === "application_rejected" ||
        event === "application_submitted"
      ) {
        fetchApplications()
      }
    })
    return () => closeSSE()
  }, [fetchApplications])

  // Keyboard shortcuts: A = navigate to first pending, X = reject first pending
  useEffect(() => {
    const pendingApps = applications.filter(a => a.status === "pending_human_review")
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return
      if (pendingApps.length === 0) return
      const first = pendingApps[0]
      if (e.key === "a" || e.key === "A") router.push(`/review?id=${first.id}`)
      if (e.key === "x" || e.key === "X") handleReject(first.id)
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [applications])

  const handleReject = async (id: number) => {
    if (actionInProgress) return
    setActionInProgress(id)
    try {
      await api.rejectApplication(id)
      setApplications(prev =>
        prev.map(a => a.id === id ? { ...a, status: "rejected" as const } : a)
      )
    } catch {
      toast.error("Failed to reject application")
    } finally {
      setActionInProgress(null)
    }
  }

  const handleCardClick = (app: Application) => {
    router.push(`/review?id=${app.id}`)
  }

  const getColumnApps = (status: string) =>
    applications.filter(a => a.status === status)

  const totalPending = applications.filter(a => a.status === "pending_human_review").length

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Applications</h1>
          <p className="text-sm text-[#8E8E93] mt-0.5">
            {loading ? "Loading..." : `${applications.length} total`}
            {totalPending > 0 && (
              <span className="text-amber-400 ml-2">· {totalPending} pending review</span>
            )}
          </p>
        </div>
        {totalPending > 0 && (
          <p className="text-xs text-[#8E8E93]">
            Press <kbd className="bg-white/5 px-1.5 py-0.5 rounded text-white">A</kbd> to review ·{" "}
            <kbd className="bg-white/5 px-1.5 py-0.5 rounded text-white">X</kbd> to reject first pending
          </p>
        )}
      </div>

      {/* Kanban Board */}
      {loading ? (
        <div className="flex gap-3 overflow-x-auto pb-4">
          {COLUMNS.map(col => (
            <div key={col.status} className="min-w-[240px] max-w-[300px] bg-white/5 rounded-2xl h-64 animate-pulse flex-shrink-0" />
          ))}
        </div>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-4">
          {COLUMNS.map(col => (
            <KanbanColumn
              key={col.status}
              status={col.status}
              label={col.label}
              accent={col.accent}
              apps={getColumnApps(col.status)}
              onReject={handleReject}
              onCardClick={handleCardClick}
            />
          ))}
        </div>
      )}
    </div>
  )
}
