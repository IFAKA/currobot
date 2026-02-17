"use client"
import { useEffect, useState, useRef, useCallback } from "react"
import { motion, AnimatePresence } from "motion/react"
import { useRouter } from "next/navigation"
import {
  CheckCircle2, XCircle, ChevronRight, ChevronLeft,
  Cpu, HardDrive, Download, Upload, FileText, Bot, AlertTriangle, Power
} from "lucide-react"
import { invoke } from "@tauri-apps/api/core"
import { api } from "@/lib/api"
import type { SetupStatus, SystemHealth } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const BASE = "http://localhost:8000"

const STEPS = [
  { id: 1, label: "System Check", icon: <Cpu className="h-4 w-4" /> },
  { id: 2, label: "RAM & Model",  icon: <HardDrive className="h-4 w-4" /> },
  { id: 3, label: "Download",     icon: <Download className="h-4 w-4" /> },
  { id: 4, label: "Upload CV",    icon: <Upload className="h-4 w-4" /> },
  { id: 5, label: "Terms",        icon: <FileText className="h-4 w-4" /> },
  { id: 6, label: "Startup",      icon: <Power className="h-4 w-4" /> },
]

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-center gap-2">
      {STEPS.map((step, i) => {
        const done = i < current - 1
        const active = i === current - 1
        return (
          <div key={step.id} className="flex items-center gap-2">
            <motion.div
              className={cn(
                "w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-colors",
                done ? "bg-[#34C759] text-white" :
                active ? "bg-[#007AFF] text-white" :
                "bg-white/5 text-[#8E8E93]"
              )}
              animate={{ scale: active ? 1.1 : 1 }}
              transition={{ type: "spring", stiffness: 300, damping: 25 }}
            >
              {done ? <CheckCircle2 className="h-4 w-4" /> : step.icon}
            </motion.div>
            {i < STEPS.length - 1 && (
              <div className={cn(
                "w-8 h-0.5 rounded-full transition-colors",
                done ? "bg-[#34C759]" : "bg-white/10"
              )} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function CheckItem({
  label,
  ok,
  loading,
}: {
  label: string
  ok: boolean | null
  loading?: boolean
}) {
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="w-5 h-5 flex items-center justify-center">
        {loading ? (
          <div className="w-4 h-4 rounded-full border-2 border-[#007AFF] border-t-transparent animate-spin" />
        ) : ok ? (
          <CheckCircle2 className="h-4 w-4 text-[#34C759]" />
        ) : (
          <XCircle className="h-4 w-4 text-[#FF3B30]" />
        )}
      </div>
      <span className={cn(
        "text-sm",
        loading ? "text-[#8E8E93]" :
        ok ? "text-white" : "text-[#FF3B30]"
      )}>
        {label}
      </span>
    </div>
  )
}

// Step 1: System Check
function Step1({
  setupStatus,
  loading,
}: {
  setupStatus: SetupStatus | null
  loading: boolean
}) {
  const ollamaOk = setupStatus?.ollama_running ?? null
  const systemOk = setupStatus?.system_check ?? null

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-white">System Check</h2>
        <p className="text-sm text-[#8E8E93] mt-1">
          Verifying that your system meets all requirements for JobBot.
        </p>
      </div>

      <div className="bg-white/5 border border-white/10 rounded-2xl p-4 space-y-1">
        <CheckItem label="Python 3.11+" ok={systemOk} loading={loading} />
        <CheckItem label="Node 20+" ok={systemOk} loading={loading} />
        <CheckItem label="Ollama running" ok={ollamaOk} loading={loading} />
      </div>

      {setupStatus && !setupStatus.system_check && (
        <div className="bg-[#FF3B30]/10 border border-[#FF3B30]/20 rounded-xl px-3 py-2 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-[#FF3B30] mt-0.5 shrink-0" />
          <p className="text-xs text-[#FF3B30]">
            System requirements not met. Ensure Python 3.11+ and Node 20+ are installed.
          </p>
        </div>
      )}

      {setupStatus && !setupStatus.ollama_running && (
        <div className="bg-amber-400/10 border border-amber-400/20 rounded-xl px-3 py-3 space-y-1.5">
          <p className="text-xs font-semibold text-amber-400">Ollama not detected</p>
          <p className="text-xs text-amber-400">
            Install Ollama from{" "}
            <a
              href="https://ollama.ai"
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
            >
              https://ollama.ai
            </a>{" "}
            then run:
          </p>
          <code className="block bg-black/30 rounded-lg px-3 py-1.5 text-xs text-[#007AFF] font-mono">
            ollama serve
          </code>
        </div>
      )}
    </div>
  )
}

// Step 2: RAM & Model
function Step2({ health }: { health: SystemHealth | null }) {
  const getRecommendation = (gb: number) => {
    if (gb >= 32) return { model: "mistral-nemo", note: "Best Spanish quality" }
    if (gb >= 16) return { model: "qwen2.5:7b", note: "Good Spanish, fits comfortably" }
    return { model: "llama3.1:8b", note: "Acceptable quality" }
  }

  const total = health?.ram_total_gb ?? 0
  const available = health?.ram_available_gb ?? 0
  const rec = getRecommendation(total)
  const usedPct = total > 0 ? ((total - available) / total) * 100 : 0

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-white">RAM & Model Selection</h2>
        <p className="text-sm text-[#8E8E93] mt-1">
          Your system specs determine the best AI model for CV generation.
        </p>
      </div>

      {health ? (
        <>
          {/* RAM Bar */}
          <div className="bg-white/5 border border-white/10 rounded-2xl p-4 space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-[#8E8E93]">Total RAM</span>
              <span className="text-white font-semibold">{total.toFixed(1)} GB</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-[#8E8E93]">Available</span>
              <span className="text-white font-semibold">{available.toFixed(1)} GB</span>
            </div>
            {/* RAM usage bar */}
            <div className="space-y-1">
              <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-[#007AFF] rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${usedPct}%` }}
                  transition={{ type: "spring", stiffness: 60, damping: 18, delay: 0.2 }}
                />
              </div>
              <div className="flex justify-between text-[11px] text-[#8E8E93]">
                <span>0 GB</span>
                <span>{total.toFixed(1)} GB total</span>
              </div>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-[#8E8E93]">Disk Free</span>
              <span className="text-white font-semibold">{health.disk_free_gb.toFixed(1)} GB</span>
            </div>
          </div>

          {/* Model Recommendation Card */}
          <div className="bg-[#007AFF]/10 border border-[#007AFF]/20 rounded-2xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <Bot className="h-4 w-4 text-[#007AFF]" />
              <span className="text-sm font-semibold text-[#007AFF]">Recommended Model</span>
            </div>
            <p className="text-xl font-bold text-white">{rec.model}</p>
            <p className="text-xs text-[#8E8E93] mt-1">{rec.note}</p>
            <p className="text-xs text-[#8E8E93] mt-2">
              Run:{" "}
              <code className="text-[#007AFF] bg-[#007AFF]/10 px-1.5 py-0.5 rounded font-mono">
                ollama pull {rec.model}
              </code>
            </p>
          </div>
        </>
      ) : (
        <div className="h-32 bg-white/5 rounded-2xl animate-pulse" />
      )}
    </div>
  )
}

// Step 3: Model Download
function Step3({
  setupStatus,
  onRefresh,
}: {
  setupStatus: SetupStatus | null
  onRefresh: () => void
}) {
  const [progress, setProgress] = useState(0)
  const [done, setDone] = useState(false)
  const [pulling, setPulling] = useState(false)
  const [modelName, setModelName] = useState("qwen2.5:7b")

  useEffect(() => {
    if (setupStatus?.model_downloaded) {
      setProgress(100)
      setDone(true)
    }
  }, [setupStatus])

  const startPull = async () => {
    setPulling(true)
    try {
      await fetch(`${BASE}/api/setup/pull-model`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelName }),
      })
      // Simulate progress bar over 30s
      let elapsed = 0
      const interval = setInterval(() => {
        elapsed += 0.5
        const pct = Math.min((elapsed / 30) * 100, 95)
        setProgress(pct)
        onRefresh()
        if (elapsed >= 30 || done) clearInterval(interval)
      }, 500)
    } catch {
      // silent — user can also run manually
    } finally {
      setPulling(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-white">Download AI Model</h2>
        <p className="text-sm text-[#8E8E93] mt-1">
          Download the Ollama model for CV adaptation. This may take several minutes depending on
          your internet connection.
        </p>
      </div>

      <div className="bg-white/5 border border-white/10 rounded-2xl p-5 space-y-4">
        {/* Model name input */}
        <div className="space-y-1.5">
          <label className="text-xs text-[#8E8E93]">Model Name</label>
          <input
            type="text"
            value={modelName}
            onChange={e => setModelName(e.target.value)}
            disabled={done || pulling}
            className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white outline-none focus:border-[#007AFF] transition-colors disabled:opacity-50"
          />
        </div>

        <div className="flex items-center gap-2">
          <div className={cn(
            "w-2 h-2 rounded-full",
            done ? "bg-[#34C759]" : pulling ? "bg-[#007AFF] animate-pulse" : "bg-white/20"
          )} />
          <span className="text-sm text-white">
            {done
              ? "Model downloaded successfully"
              : pulling
              ? "Downloading model..."
              : "Model not yet downloaded"}
          </span>
        </div>

        {/* Progress bar */}
        <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
          <motion.div
            className={cn("h-full rounded-full", done ? "bg-[#34C759]" : "bg-[#007AFF]")}
            animate={{ width: `${progress}%` }}
            transition={{ type: "spring", stiffness: 80, damping: 25 }}
          />
        </div>

        {!done && (
          <Button
            onClick={startPull}
            loading={pulling}
            disabled={done}
            className="w-full"
          >
            <Download className="h-4 w-4" />
            Download Model
          </Button>
        )}
      </div>

      {done && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-[#34C759]/10 border border-[#34C759]/20 rounded-xl p-3 flex items-center gap-2"
        >
          <CheckCircle2 className="h-4 w-4 text-[#34C759]" />
          <p className="text-sm text-[#34C759]">Model is ready. You can proceed.</p>
        </motion.div>
      )}

      {!done && (
        <button
          onClick={onRefresh}
          className="text-xs text-[#8E8E93] underline hover:text-white transition-colors"
        >
          Skip (model already downloaded)
        </button>
      )}
    </div>
  )
}

// Step 4: CV Upload
function Step4({ onUploaded }: { onUploaded: () => void }) {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [done, setDone] = useState(false)
  const [filename, setFilename] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (file: File) => {
    if (!file.name.endsWith(".pdf")) {
      setError("Please upload a .pdf file")
      return
    }
    setUploading(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append("file", file)
      const res = await fetch(`${BASE}/api/setup/upload-cv`, { method: "POST", body: fd })
      if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`)
      setDone(true)
      setFilename(file.name)
      onUploaded()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed")
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-white">Upload Master CV</h2>
        <p className="text-sm text-[#8E8E93] mt-1">
          Upload your base CV as a PDF. It stays on your device and is adapted locally by the AI.
        </p>
      </div>

      <div
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault()
          setDragging(false)
          const f = e.dataTransfer.files[0]
          if (f) handleFile(f)
        }}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "border-2 border-dashed rounded-2xl p-12 flex flex-col items-center justify-center cursor-pointer transition-all",
          dragging ? "border-[#007AFF] bg-[#007AFF]/10" :
          done ? "border-[#34C759]/40 bg-[#34C759]/5" :
          "border-white/10 hover:border-white/20 hover:bg-white/[0.03]"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
        />
        {done && filename ? (
          <motion.div
            initial={{ scale: 0.8 }}
            animate={{ scale: 1 }}
            transition={{ type: "spring" }}
            className="flex flex-col items-center gap-2"
          >
            <CheckCircle2 className="h-12 w-12 text-[#34C759]" />
            <p className="text-sm font-semibold text-[#34C759]">{filename}</p>
            <p className="text-xs text-[#34C759]/70">uploaded successfully</p>
          </motion.div>
        ) : (
          <>
            <Upload className={cn(
              "h-10 w-10 mb-3",
              dragging ? "text-[#007AFF]" : "text-[#8E8E93]"
            )} />
            <p className="text-sm font-medium text-white">
              {uploading ? "Uploading..." : "Drop your CV here (PDF)"}
            </p>
            <p className="text-xs text-[#8E8E93] mt-1">or click to browse · PDF only</p>
          </>
        )}
        {error && <p className="text-xs text-[#FF3B30] mt-3">{error}</p>}
      </div>
    </div>
  )
}

// Step 5: Terms of Service
function Step5({
  accepted,
  onAccept,
}: {
  accepted: boolean
  onAccept: (v: boolean) => void
}) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-white">Before You Start</h2>
        <p className="text-sm text-[#8E8E93] mt-1">
          Please read and accept the terms before using JobBot.
        </p>
      </div>

      <div className="bg-white/5 border border-white/10 rounded-2xl p-4 text-xs text-[#8E8E93] space-y-3 max-h-64 overflow-y-auto">
        <p className="font-semibold text-white">JobBot Terms of Service</p>

        <p>
          JobBot is a personal automation tool. By using it, you acknowledge:
        </p>

        <ul className="space-y-2 list-none">
          <li className="flex items-start gap-2">
            <span className="text-[#007AFF] mt-0.5">•</span>
            <span>
              You are responsible for complying with the Terms of Service of each job platform you scrape.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-[#007AFF] mt-0.5">•</span>
            <span>
              Job applications submitted through JobBot are submitted on your behalf. You authorize each
              submission individually.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-[#007AFF] mt-0.5">•</span>
            <span>
              JobBot stores your CV and job data locally on this device. No data is sent to external
              servers unless you configure a non-local Ollama endpoint.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-[#007AFF] mt-0.5">•</span>
            <span>
              JobBot is provided as-is with no warranty. Use at your own discretion.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-[#007AFF] mt-0.5">•</span>
            <span>
              Web scraping may violate some platforms&apos; ToS. You accept full responsibility for your use.
            </span>
          </li>
        </ul>
      </div>

      <label className="flex items-center gap-3 cursor-pointer select-none">
        <div
          onClick={() => onAccept(!accepted)}
          className={cn(
            "w-5 h-5 rounded border-2 flex items-center justify-center transition-colors shrink-0",
            accepted ? "bg-[#007AFF] border-[#007AFF]" : "border-white/20 hover:border-white/40"
          )}
        >
          {accepted && <CheckCircle2 className="h-3.5 w-3.5 text-white" />}
        </div>
        <span className="text-sm text-white">
          I have read and accept these terms
        </span>
      </label>
    </div>
  )
}

// Step 6: Startup Preference
function Step6({
  autolaunchEnabled,
  onToggle,
  isTauriApp,
}: {
  autolaunchEnabled: boolean
  onToggle: (v: boolean) => void
  isTauriApp: boolean
}) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-white">Startup Preference</h2>
        <p className="text-sm text-[#8E8E93] mt-1">
          Should JobBot start automatically when you log in?
        </p>
      </div>

      <div className="bg-white/5 border border-white/10 rounded-2xl p-4 space-y-4">
        {isTauriApp ? (
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-white">Start on login</p>
              <p className="text-xs text-[#8E8E93] mt-0.5">
                JobBot will run in the tray when you log in
              </p>
            </div>
            <button
              onClick={() => onToggle(!autolaunchEnabled)}
              className={cn(
                "relative w-11 h-6 rounded-full transition-colors shrink-0",
                autolaunchEnabled ? "bg-[#34C759]" : "bg-white/10"
              )}
            >
              <motion.span
                layout
                className="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-sm"
                animate={{ x: autolaunchEnabled ? 20 : 0 }}
                transition={{ type: "spring", stiffness: 400, damping: 30 }}
              />
            </button>
          </div>
        ) : (
          <p className="text-sm text-[#8E8E93]">
            Autolaunch is configured via the tray icon in the desktop app.
          </p>
        )}
        <p className="text-xs text-[#8E8E93]">
          You can change this at any time from the tray menu.
        </p>
      </div>
    </div>
  )
}

export default function SetupPage() {
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null)
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [cvUploaded, setCvUploaded] = useState(false)
  const [tosAccepted, setTosAccepted] = useState(false)
  const [completing, setCompleting] = useState(false)
  const [autolaunchEnabled, setAutolaunchEnabled] = useState(false)
  const [isTauriApp, setIsTauriApp] = useState(false)

  useEffect(() => {
    setIsTauriApp("__TAURI_INTERNALS__" in window)
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      const [s, h] = await Promise.allSettled([
        api.getSetupStatus(),
        api.getHealth(),
      ])
      if (s.status === "fulfilled") {
        setSetupStatus(s.value)
        // If already completed, redirect
        if (s.value.setup_complete) {
          router.push("/")
          return
        }
      }
      if (h.status === "fulfilled") setHealth(h.value)
    } finally {
      setLoading(false)
    }
  }, [router])

  useEffect(() => {
    refreshStatus()
  }, [refreshStatus])

  const canProceed = (): boolean => {
    switch (step) {
      case 1: return Boolean(setupStatus?.system_check && setupStatus?.ollama_running)
      case 2: return true
      case 3: return Boolean(setupStatus?.model_downloaded)
      case 4: return cvUploaded || Boolean(setupStatus?.cv_uploaded)
      case 5: return tosAccepted
      case 6: return true
      default: return false
    }
  }

  const handleNext = async () => {
    if (step < 5) {
      setStep(s => s + 1)
    } else if (step === 5) {
      setCompleting(true)
      try {
        await api.acceptTos()
        setStep(6)
      } catch {
        // silent
      } finally {
        setCompleting(false)
      }
    } else {
      // step 6: apply autolaunch choice then complete
      setCompleting(true)
      try {
        if (isTauriApp) {
          try { await invoke("set_autolaunch", { enabled: autolaunchEnabled }) } catch { /* silent */ }
        }
        await api.completeSetup()
        router.push("/")
      } catch {
        setCompleting(false)
      }
    }
  }

  const handleBack = () => {
    if (step > 1) setStep(s => s - 1)
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#1C1C1E] flex items-center justify-center">
        <div className="w-8 h-8 rounded-full border-2 border-[#007AFF] border-t-transparent animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#1C1C1E] flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-lg space-y-8">
        {/* Logo */}
        <div className="flex flex-col items-center gap-2">
          <div className="w-12 h-12 rounded-2xl bg-[#007AFF] flex items-center justify-center">
            <Bot className="h-6 w-6 text-white" />
          </div>
          <h1 className="text-xl font-bold text-white">JobBot Setup</h1>
          <p className="text-sm text-[#8E8E93]">Step {step} of {STEPS.length}</p>
        </div>

        {/* Step Indicators */}
        <div className="flex justify-center">
          <StepIndicator current={step} />
        </div>

        {/* Progress bar */}
        <div className="h-0.5 bg-white/5 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-[#007AFF] rounded-full"
            animate={{ width: `${((step - 1) / (STEPS.length - 1)) * 100}%` }}
            transition={{ type: "spring", stiffness: 80, damping: 20 }}
          />
        </div>

        {/* Step content with animated transitions */}
        <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ type: "spring", stiffness: 250, damping: 25 }}
            >
              {step === 1 && <Step1 setupStatus={setupStatus} loading={loading} />}
              {step === 2 && <Step2 health={health} />}
              {step === 3 && <Step3 setupStatus={setupStatus} onRefresh={refreshStatus} />}
              {step === 4 && <Step4 onUploaded={() => setCvUploaded(true)} />}
              {step === 5 && <Step5 accepted={tosAccepted} onAccept={setTosAccepted} />}
              {step === 6 && (
                <Step6
                  autolaunchEnabled={autolaunchEnabled}
                  onToggle={setAutolaunchEnabled}
                  isTauriApp={isTauriApp}
                />
              )}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between">
          <Button
            variant="ghost"
            onClick={handleBack}
            disabled={step === 1}
          >
            <ChevronLeft className="h-4 w-4" />
            Back
          </Button>

          <Button
            onClick={handleNext}
            disabled={!canProceed()}
            loading={completing}
            size="lg"
          >
            {step === 6 ? "Complete Setup" : "Next"}
            {step < 5 && <ChevronRight className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  )
}
