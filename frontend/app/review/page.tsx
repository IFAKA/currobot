"use client"
import { Suspense } from "react"
import { useEffect, useState, useCallback } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { motion, AnimatePresence } from "motion/react"
import {
  CheckCircle2, XCircle, ArrowLeft, AlertTriangle,
  ExternalLink, Clock, Image as ImageIcon
} from "lucide-react"
import { api } from "@/lib/api"
import { playSuccess, playError } from "@/lib/sounds"
import type { Application } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { toast } from "@/lib/toast"
import { StatusBadge, ProfilePill } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { formatDate, cn } from "@/lib/utils"

const BASE = "http://localhost:8000"

function QualityRing({ score }: { score: number | null }) {
  if (score === null) return <span className="text-[#8E8E93] text-2xl font-bold">—</span>
  const color =
    score >= 8 ? "#34C759" :
    score >= 5 ? "#F59E0B" :
    "#FF3B30"
  const pct = (score / 10) * 100
  const r = 20
  const circ = 2 * Math.PI * r
  const dash = (pct / 100) * circ

  return (
    <div className="relative flex items-center justify-center w-16 h-16">
      <svg className="w-16 h-16 -rotate-90" viewBox="0 0 48 48">
        <circle cx="24" cy="24" r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="4" />
        <motion.circle
          cx="24" cy="24" r={r}
          fill="none"
          stroke={color}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={circ}
          initial={{ strokeDashoffset: circ }}
          animate={{ strokeDashoffset: circ - dash }}
          transition={{ type: "spring", stiffness: 60, damping: 18, delay: 0.2 }}
        />
      </svg>
      <span className="absolute text-sm font-bold" style={{ color }}>{score}/10</span>
    </div>
  )
}

function JsonHighlight({ data }: { data: Record<string, unknown> }) {
  return (
    <pre className="text-xs leading-relaxed overflow-x-auto whitespace-pre-wrap break-all">
      <span className="text-white/40">{"{\n"}</span>
      {Object.entries(data).map(([key, value], i, arr) => {
        const isLast = i === arr.length - 1
        const comma = isLast ? "" : ","
        const isString = typeof value === "string"
        const isNumber = typeof value === "number"
        const rendered = isString
          ? `"${value}"`
          : value === null
          ? "null"
          : typeof value === "object"
          ? JSON.stringify(value, null, 2)
          : String(value)
        return (
          <span key={key}>
            <span className="text-[#8E8E93]">{"  "}&quot;{key}&quot;</span>
            <span className="text-white/40">: </span>
            <span className={isString ? "text-[#34C759]" : isNumber ? "text-[#007AFF]" : "text-white/70"}>
              {rendered}
            </span>
            <span className="text-white/40">{comma}{"\n"}</span>
          </span>
        )
      })}
      <span className="text-white/40">{"}"}</span>
    </pre>
  )
}

function SessionCountdown({ authorizedAt }: { authorizedAt: string | null }) {
  const [minutesLeft, setMinutesLeft] = useState<number | null>(null)

  useEffect(() => {
    if (!authorizedAt) return
    const update = () => {
      const expiry = new Date(authorizedAt).getTime() + 25 * 60 * 1000
      const left = Math.floor((expiry - Date.now()) / 60000)
      setMinutesLeft(left)
    }
    update()
    const interval = setInterval(update, 30000)
    return () => clearInterval(interval)
  }, [authorizedAt])

  if (minutesLeft === null || minutesLeft > 10) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-amber-400/10 border border-amber-400/20 rounded-xl px-3 py-2 flex items-center gap-2"
    >
      <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
      <span className="text-sm text-amber-400">
        Session expires in ~{Math.max(0, minutesLeft)} min
      </span>
    </motion.div>
  )
}

type ExtendedApplication = Application & {
  title?: string
  cv_adapted_json?: Record<string, unknown>
  form_fields_json?: Record<string, string>
}

function ReviewContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const appId = Number(searchParams.get("id"))

  const [app, setApp] = useState<ExtendedApplication | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [authorizing, setAuthorizing] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [formFields, setFormFields] = useState<Record<string, string>>({})
  const [successVisible, setSuccessVisible] = useState(false)
  const [flashColor, setFlashColor] = useState<"green" | "red" | null>(null)

  const fetchApp = useCallback(async () => {
    try {
      const res = await api.getApplications()
      const found = res.items.find(a => a.id === appId) as ExtendedApplication | undefined
      if (!found) {
        const pending = await api.getPendingReviews()
        const foundPending = pending.items.find(a => a.id === appId) as ExtendedApplication | undefined
        if (foundPending) {
          setApp(foundPending)
          if (foundPending.form_fields_json) setFormFields(foundPending.form_fields_json)
          return
        }
        throw new Error("Application not found")
      }
      setApp(found)
      if (found.form_fields_json) setFormFields(found.form_fields_json)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load application")
    } finally {
      setLoading(false)
    }
  }, [appId])

  useEffect(() => { fetchApp() }, [fetchApp])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") router.back()
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleAuthorize()
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app])

  const handleAuthorize = async () => {
    if (!app || authorizing) return
    setAuthorizing(true)
    try {
      await api.authorizeApplication(app.id)
      playSuccess()
      setFlashColor("green")
      setTimeout(() => setFlashColor(null), 600)
      setSuccessVisible(true)
      setTimeout(() => router.push("/applications"), 2000)
    } catch {
      playError()
      toast.error("Failed to authorize application")
    } finally {
      setAuthorizing(false)
    }
  }

  const handleReject = async () => {
    if (!app || rejecting) return
    setRejecting(true)
    try {
      await api.rejectApplication(app.id)
      router.push("/applications")
    } catch {
      playError()
      setFlashColor("red")
      setTimeout(() => setFlashColor(null), 600)
      toast.error("Failed to reject application")
    } finally {
      setRejecting(false)
    }
  }

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto space-y-4">
        <div className="h-8 bg-white/5 rounded-xl animate-pulse w-48" />
        <div className="flex items-center gap-4">
          <div className="h-16 w-16 bg-white/5 rounded-full animate-pulse" />
          <div className="space-y-2 flex-1">
            <div className="h-6 bg-white/5 rounded w-48 animate-pulse" />
            <div className="h-4 bg-white/5 rounded w-32 animate-pulse" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="h-96 bg-white/5 rounded-2xl animate-pulse" />
          <div className="h-96 bg-white/5 rounded-2xl animate-pulse" />
        </div>
      </div>
    )
  }

  if (error || !app) {
    return (
      <div className="max-w-5xl mx-auto">
        <Card className="text-center py-12">
          <XCircle className="h-10 w-10 text-[#FF3B30] mx-auto mb-3" />
          <p className="text-white">{error ?? "Application not found"}</p>
          <Button variant="outline" className="mt-4" onClick={() => router.back()}>
            <ArrowLeft className="h-4 w-4" />
            Go back
          </Button>
        </Card>
      </div>
    )
  }

  const screenshotUrl = app.form_screenshot_path
    ? `${BASE}/api/screenshots/${encodeURIComponent(app.form_screenshot_path)}`
    : null

  return (
    <div className={cn(
      "max-w-6xl mx-auto space-y-5 rounded-2xl transition-colors duration-500",
      flashColor === "green" && "bg-green-950/30",
      flashColor === "red"   && "bg-red-950/30",
    )}>
      <AnimatePresence>
        {successVisible && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          >
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 20 }}
              transition={{ type: "spring", stiffness: 260, damping: 22 }}
              className="text-center"
            >
              <CheckCircle2
                className="h-24 w-24 text-[#34C759] mx-auto mb-4"
                style={{ animation: "bounce-in 350ms cubic-bezier(0.34, 1.56, 0.64, 1) 100ms backwards" }}
              />
              <h2
                className="text-3xl font-bold text-white"
                style={{ animation: "slide-up-in 260ms ease-out 300ms backwards" }}
              >
                Application submitted!
              </h2>
              <p
                className="text-[#8E8E93] mt-2"
                style={{ animation: "slide-up-in 260ms ease-out 380ms backwards" }}
              >
                Redirecting to applications...
              </p>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <button
        onClick={() => router.back()}
        className="flex items-center gap-1.5 text-sm text-[#8E8E93] hover:text-white transition-colors active:scale-95 transition-transform"
      >
        <ArrowLeft className="h-4 w-4" />
        Applications
      </button>

      <div className="flex items-center gap-4 flex-wrap">
        <QualityRing score={app.quality_score} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-bold text-white">{app.company}</h1>
            {app.title && (
              <span className="text-[#8E8E93] text-sm">— {app.title}</span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <StatusBadge status={app.status} />
            <ProfilePill profile={app.cv_profile} />
            <span className="text-xs text-[#8E8E93]">
              Created {formatDate(app.created_at)}
            </span>
          </div>
        </div>
        {app.form_url && (
          <a href={app.form_url} target="_blank" rel="noopener noreferrer">
            <Button size="sm" variant="outline">
              <ExternalLink className="h-3.5 w-3.5" />
              Open form
            </Button>
          </a>
        )}
      </div>

      <SessionCountdown authorizedAt={app.authorized_at} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="lg:sticky lg:top-4 self-start">
          <Card className="flex flex-col gap-3">
            <div className="flex items-center gap-2 mb-1">
              <ImageIcon className="h-4 w-4 text-[#8E8E93]" />
              <span className="text-sm font-semibold text-white">Form Screenshot</span>
            </div>
            {screenshotUrl ? (
              <div className="rounded-xl overflow-hidden border border-white/5">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={screenshotUrl}
                  alt="Form screenshot"
                  className="w-full object-contain max-h-[500px]"
                />
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-64 bg-white/[0.03] rounded-xl border border-dashed border-white/10">
                <ImageIcon className="h-10 w-10 text-[#8E8E93] mb-2" />
                <p className="text-sm text-[#8E8E93]">No screenshot available</p>
              </div>
            )}
          </Card>
        </div>

        <Card className="flex flex-col gap-3 overflow-hidden">
          <div className="flex items-center gap-2 mb-1">
            <Clock className="h-4 w-4 text-[#8E8E93]" />
            <span className="text-sm font-semibold text-white">CV Adaptation</span>
          </div>
          <div className="flex-1 overflow-y-auto max-h-[500px] bg-white/[0.03] rounded-xl p-3">
            {app.cv_adapted_json ? (
              <JsonHighlight data={app.cv_adapted_json} />
            ) : (
              <div className="text-sm text-[#8E8E93] text-center py-8">
                CV data not available yet
              </div>
            )}
          </div>
        </Card>
      </div>

      {Object.keys(formFields).length > 0 && (
        <Card>
          <h3 className="text-sm font-semibold text-white mb-3">Form Fields</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.entries(formFields).map(([key, value]) => (
              <div key={key} className="space-y-1">
                <label className="text-xs text-[#8E8E93] capitalize">
                  {key.replace(/_/g, " ")}
                </label>
                <input
                  type="text"
                  value={value}
                  onChange={e => setFormFields(f => ({ ...f, [key]: e.target.value }))}
                  className={cn(
                    "w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2",
                    "text-sm text-white outline-none",
                    "focus:border-[#007AFF] transition-colors"
                  )}
                />
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="sticky bottom-4 flex items-center justify-between gap-3 bg-[#2C2C2E]/90 backdrop-blur-sm border border-white/10 rounded-2xl p-3">
        <p className="text-xs text-[#8E8E93]">
          <kbd className="bg-white/5 px-1.5 py-0.5 rounded text-white text-[11px]">⌘↵</kbd> Authorize ·{" "}
          <kbd className="bg-white/5 px-1.5 py-0.5 rounded text-white text-[11px]">Esc</kbd> Back
        </p>
        <div className="flex items-center gap-2">
          <Button variant="destructive" loading={rejecting} onClick={handleReject}>
            <XCircle className="h-4 w-4" />
            ✕ Reject
          </Button>
          <Button variant="success" loading={authorizing} onClick={handleAuthorize}>
            <CheckCircle2 className="h-4 w-4" />
            ⌘↵ Authorize Submission
          </Button>
        </div>
      </div>
    </div>
  )
}

export default function ReviewPage() {
  return (
    <Suspense fallback={
      <div className="max-w-5xl mx-auto space-y-4">
        <div className="h-8 bg-white/5 rounded-xl animate-pulse w-48" />
      </div>
    }>
      <ReviewContent />
    </Suspense>
  )
}
