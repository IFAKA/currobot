"use client"
import { useEffect, useState, useCallback } from "react"
import { motion, AnimatePresence } from "motion/react"
import {
  Cpu, Globe, Clock, Trash2, Building2, XCircle,
  Plus, Save, CheckCircle2, AlertTriangle, Volume2,
  Database, FileText, ChevronDown, Power
} from "lucide-react"
import { invoke } from "@tauri-apps/api/core"
import { api } from "@/lib/api"
import { playSuccess, playError } from "@/lib/sounds"
import type { CompanySource } from "@/lib/types"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const BASE = "http://localhost:8000"

const SCRAPER_TYPES = [
  "career_page",
  "greenhouse",
  "lever",
  "teamtailor",
  "personio",
  "workday",
]

const CV_PROFILES = ["cashier", "stocker", "logistics", "frontend_dev", "fullstack_dev"]

function SectionHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="text-[#007AFF]">{icon}</span>
      <h2 className="text-base font-semibold text-white">{title}</h2>
    </div>
  )
}

function SettingInput({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  warning,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
  warning?: boolean
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs text-[#8E8E93] font-medium">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className={cn(
          "w-full bg-white/5 border rounded-xl px-3 py-2 text-sm text-white outline-none transition-colors",
          "placeholder:text-[#8E8E93] focus:border-[#007AFF]",
          warning ? "border-amber-400/50" : "border-white/10"
        )}
      />
    </div>
  )
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-white">{label}</span>
      <button
        onClick={() => onChange(!checked)}
        className={cn(
          "relative w-11 h-6 rounded-full transition-colors",
          checked ? "bg-[#007AFF]" : "bg-white/10"
        )}
      >
        <motion.span
          layout
          className="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-sm"
          animate={{ x: checked ? 20 : 0 }}
          transition={{ type: "spring", stiffness: 400, damping: 30 }}
        />
      </button>
    </div>
  )
}

function AddSourceForm({
  onClose,
  onAdd,
}: {
  onClose: () => void
  onAdd: (source: Partial<CompanySource>) => Promise<void>
}) {
  const [form, setForm] = useState({
    company_name: "",
    source_url: "",
    scraper_type: "career_page",
    cv_profile: "cashier",
    css_selector: "",
    enabled: true,
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    if (!form.company_name || !form.source_url) {
      setError("Company name and URL are required")
      return
    }
    setSaving(true)
    try {
      await onAdd({
        company_name: form.company_name,
        source_url: form.source_url,
        scraper_type: form.scraper_type,
        cv_profile: form.cv_profile,
        enabled: form.enabled,
      })
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add source")
    } finally {
      setSaving(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.95, y: 10 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.95, y: 10 }}
        transition={{ type: "spring", stiffness: 300, damping: 25 }}
        className="bg-[#2C2C2E] border border-white/10 rounded-2xl p-5 w-full max-w-md"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-white mb-4">Add Company Source</h3>

        <div className="space-y-3">
          <SettingInput
            label="Company Name"
            value={form.company_name}
            onChange={v => setForm(f => ({ ...f, company_name: v }))}
            placeholder="Mercadona"
          />
          <SettingInput
            label="Source URL"
            value={form.source_url}
            onChange={v => setForm(f => ({ ...f, source_url: v }))}
            placeholder="https://empleo.mercadona.es/jobs"
          />

          {/* Scraper Type */}
          <div className="space-y-1.5">
            <label className="text-xs text-[#8E8E93] font-medium">Scraper Type</label>
            <div className="relative">
              <select
                value={form.scraper_type}
                onChange={e => setForm(f => ({ ...f, scraper_type: e.target.value }))}
                className="w-full appearance-none bg-white/5 border border-white/10 rounded-xl px-3 py-2 pr-7 text-sm text-white outline-none"
              >
                {SCRAPER_TYPES.map(t => (
                  <option key={t} value={t} className="bg-[#2C2C2E]">
                    {t.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
              <ChevronDown className="h-3 w-3 text-[#8E8E93] absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
          </div>

          {/* CSS Selector (optional) */}
          <SettingInput
            label="CSS Selector (optional)"
            value={form.css_selector}
            onChange={v => setForm(f => ({ ...f, css_selector: v }))}
            placeholder=".job-listing-item"
          />

          {/* CV Profile */}
          <div className="space-y-1.5">
            <label className="text-xs text-[#8E8E93] font-medium">CV Profile</label>
            <div className="relative">
              <select
                value={form.cv_profile}
                onChange={e => setForm(f => ({ ...f, cv_profile: e.target.value }))}
                className="w-full appearance-none bg-white/5 border border-white/10 rounded-xl px-3 py-2 pr-7 text-sm text-white outline-none"
              >
                {CV_PROFILES.map(p => (
                  <option key={p} value={p} className="bg-[#2C2C2E]">
                    {p.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
              <ChevronDown className="h-3 w-3 text-[#8E8E93] absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
          </div>
        </div>

        {error && (
          <p className="text-xs text-[#FF3B30] mt-3">{error}</p>
        )}

        <div className="flex gap-2 mt-4">
          <Button variant="outline" className="flex-1" onClick={onClose}>
            Cancel
          </Button>
          <Button className="flex-1" loading={saving} onClick={handleSubmit}>
            Add Source
          </Button>
        </div>
      </motion.div>
    </motion.div>
  )
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, string>>({})
  const [sources, setSources] = useState<CompanySource[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)
  const [showAddSource, setShowAddSource] = useState(false)
  const [testingConnection, setTestingConnection] = useState(false)
  const [connectionResult, setConnectionResult] = useState<string | null>(null)
  const [backupStatus, setBackupStatus] = useState<"idle" | "running" | "done" | "coming_soon">("idle")
  const [isTauriApp, setIsTauriApp] = useState(false)
  const [autolaunchOn, setAutolaunchOn] = useState(false)

  useEffect(() => {
    const tauri = "__TAURI_INTERNALS__" in window
    setIsTauriApp(tauri)
    if (tauri) {
      invoke<boolean>("get_autolaunch_enabled").then(setAutolaunchOn).catch(() => {})
    }
  }, [])

  const handleAutolaunchToggle = async (enabled: boolean) => {
    setAutolaunchOn(enabled)
    try {
      await invoke("set_autolaunch", { enabled })
    } catch {
      setAutolaunchOn(!enabled) // revert on error
    }
  }

  // Derived settings with defaults
  const ollamaHost = settings.ollama_host ?? "http://localhost:11434"
  const ollamaModel = settings.ollama_model ?? "llama3"
  const jobsRetentionDays = settings.jobs_retention_days ?? "30"
  const appsRetentionDays = settings.apps_retention_days ?? "90"
  const soundEnabled = settings.sound_enabled !== "false"
  const lastBackup = settings.last_backup_at ?? null

  const isRemoteOllama =
    !ollamaHost.includes("localhost") && !ollamaHost.includes("127.0.0.1")

  const fetchAll = useCallback(async () => {
    try {
      const [s, c] = await Promise.allSettled([
        api.getSettings(),
        api.getCompanySources(),
      ])
      if (s.status === "fulfilled") setSettings(s.value)
      if (c.status === "fulfilled") setSources(c.value.items)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const updateSetting = (key: string, value: string) => {
    setSettings(s => ({ ...s, [key]: value }))
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.updateSettings(settings)
      playSuccess()
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch {
      playError()
    } finally {
      setSaving(false)
    }
  }

  const testConnection = async () => {
    setTestingConnection(true)
    setConnectionResult(null)
    try {
      const health = await api.getHealth()
      setConnectionResult(health.status === "ok" ? "ok" : "error")
    } catch {
      setConnectionResult("error")
    } finally {
      setTestingConnection(false)
    }
  }

  const runBackup = async () => {
    setBackupStatus("running")
    try {
      const res = await fetch(`${BASE}/api/backup`, { method: "POST" })
      if (res.ok) {
        updateSetting("last_backup_at", new Date().toISOString())
        setBackupStatus("done")
        setTimeout(() => setBackupStatus("idle"), 3000)
      } else {
        // Route not implemented yet
        setBackupStatus("coming_soon")
        setTimeout(() => setBackupStatus("idle"), 3000)
      }
    } catch {
      setBackupStatus("coming_soon")
      setTimeout(() => setBackupStatus("idle"), 3000)
    }
  }

  const handleAddSource = async (data: Partial<CompanySource>) => {
    const added = await api.addCompanySource(data)
    setSources(s => [...s, added])
  }

  const toggleSourceEnabled = (id: number, enabled: boolean) => {
    setSources(prev => prev.map(s => s.id === id ? { ...s, enabled } : s))
  }

  const deleteSource = (id: number) => {
    setSources(prev => prev.filter(s => s.id !== id))
  }

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto space-y-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-32 bg-white/5 rounded-2xl animate-pulse" />
        ))}
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto space-y-5 pb-24">
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-sm text-[#8E8E93] mt-0.5">Configure JobBot behavior</p>
      </div>

      {/* AI Model Section */}
      <Card>
        <SectionHeader icon={<Cpu className="h-4 w-4" />} title="AI Model" />
        <div className="space-y-3">
          <SettingInput
            label="Ollama Host"
            value={ollamaHost}
            onChange={v => updateSetting("ollama_host", v)}
            placeholder="http://localhost:11434"
            warning={isRemoteOllama}
          />

          {isRemoteOllama && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              className="bg-amber-400/10 border border-amber-400/20 rounded-xl px-3 py-2 flex items-center gap-2"
            >
              <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
              <p className="text-xs text-amber-400">
                CV data will be sent to an external server. Your CV and job data will leave this device.
              </p>
            </motion.div>
          )}

          <SettingInput
            label="Model Name"
            value={ollamaModel}
            onChange={v => updateSetting("ollama_model", v)}
            placeholder="llama3"
          />

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              loading={testingConnection}
              onClick={testConnection}
            >
              Test Connection
            </Button>
            {connectionResult === "ok" && (
              <span className="flex items-center gap-1 text-xs text-[#34C759]">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Connected
              </span>
            )}
            {connectionResult === "error" && (
              <span className="flex items-center gap-1 text-xs text-[#FF3B30]">
                <XCircle className="h-3.5 w-3.5" />
                Failed to connect
              </span>
            )}
          </div>
        </div>
      </Card>

      {/* Scraping Section */}
      <Card>
        <SectionHeader icon={<Globe className="h-4 w-4" />} title="Scraping" />
        <div className="space-y-3">
          <p className="text-xs text-[#8E8E93]">
            JobBot applies rate limiting between requests to avoid triggering anti-bot protections.
            Aggressive scraping may result in IP bans on job platforms.
          </p>
          <p className="text-xs text-[#8E8E93]">
            Default delay: <span className="text-white font-medium">2–6 seconds</span> between page
            requests. Adjust in the backend configuration if needed.
          </p>
        </div>
      </Card>

      {/* Data Retention */}
      <Card>
        <SectionHeader icon={<Clock className="h-4 w-4" />} title="Data Retention" />
        <div className="grid grid-cols-2 gap-4">
          <SettingInput
            label="Keep jobs for (days)"
            type="number"
            value={jobsRetentionDays}
            onChange={v => updateSetting("jobs_retention_days", v)}
            placeholder="30"
          />
          <SettingInput
            label="Keep applications for (days)"
            type="number"
            value={appsRetentionDays}
            onChange={v => updateSetting("apps_retention_days", v)}
            placeholder="90"
          />
        </div>
      </Card>

      {/* Sound */}
      <Card>
        <SectionHeader icon={<Volume2 className="h-4 w-4" />} title="Sound" />
        <Toggle
          label="Enable UI sounds"
          checked={soundEnabled}
          onChange={v => updateSetting("sound_enabled", String(v))}
        />
      </Card>

      {/* Company Sources */}
      <Card>
        <div className="flex items-center justify-between mb-3">
          <SectionHeader icon={<Building2 className="h-4 w-4" />} title="Company Sources" />
          <Button size="sm" onClick={() => setShowAddSource(true)}>
            <Plus className="h-3.5 w-3.5" />
            Add Source
          </Button>
        </div>

        {sources.length === 0 ? (
          <p className="text-sm text-[#8E8E93] text-center py-4">
            No company sources added yet.
          </p>
        ) : (
          <div className="space-y-2">
            {/* Table header */}
            <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-2 px-2 pb-1 border-b border-white/5">
              <span className="text-[11px] text-[#8E8E93]">Company</span>
              <span className="text-[11px] text-[#8E8E93]">Type</span>
              <span className="text-[11px] text-[#8E8E93]">Profile</span>
              <span className="text-[11px] text-[#8E8E93]">On</span>
              <span className="text-[11px] text-[#8E8E93]"></span>
            </div>
            {sources.map(source => (
              <motion.div
                key={source.id}
                layout
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -8 }}
                className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-2 items-center bg-white/5 rounded-xl px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="text-sm text-white font-medium truncate">{source.company_name}</p>
                  <p className="text-[11px] text-[#8E8E93] truncate">{source.source_url}</p>
                </div>
                <span className="text-xs text-[#8E8E93] bg-white/5 px-2 py-0.5 rounded-full whitespace-nowrap">
                  {source.scraper_type.replace(/_/g, " ")}
                </span>
                <span className="text-xs text-[#8E8E93] whitespace-nowrap">
                  {source.cv_profile.replace(/_/g, " ")}
                </span>
                {/* Enabled toggle */}
                <button
                  onClick={() => toggleSourceEnabled(source.id, !source.enabled)}
                  className={cn(
                    "relative w-8 h-4 rounded-full transition-colors shrink-0",
                    source.enabled ? "bg-[#007AFF]" : "bg-white/10"
                  )}
                >
                  <motion.span
                    layout
                    className="absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full shadow-sm"
                    animate={{ x: source.enabled ? 16 : 0 }}
                    transition={{ type: "spring", stiffness: 400, damping: 30 }}
                  />
                </button>
                <button
                  onClick={() => deleteSource(source.id)}
                  className="text-[#8E8E93] hover:text-[#FF3B30] transition-colors"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </motion.div>
            ))}
          </div>
        )}
      </Card>

      {/* Desktop (Tauri only) */}
      {isTauriApp && (
        <Card>
          <SectionHeader icon={<Power className="h-4 w-4" />} title="Desktop" />
          <Toggle
            label="Start on login"
            checked={autolaunchOn}
            onChange={handleAutolaunchToggle}
          />
          <p className="text-xs text-[#8E8E93] mt-2">
            You can also toggle this from the tray icon menu.
          </p>
        </Card>
      )}

      {/* Backup */}
      <Card>
        <SectionHeader icon={<Database className="h-4 w-4" />} title="Backup" />
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-white">Database Backup</p>
            <p className="text-xs text-[#8E8E93] mt-0.5">
              Stored in <code className="text-[#007AFF]">data/backups/</code> directory
            </p>
            {lastBackup && (
              <p className="text-xs text-[#8E8E93] mt-0.5">
                Last backup: {new Date(lastBackup).toLocaleString("es-ES")}
              </p>
            )}
          </div>
          <div className="flex flex-col items-end gap-1">
            <Button
              size="sm"
              variant="outline"
              loading={backupStatus === "running"}
              onClick={runBackup}
            >
              Run Backup Now
            </Button>
            {backupStatus === "done" && (
              <span className="text-xs text-[#34C759] flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" />
                Backup complete
              </span>
            )}
            {backupStatus === "coming_soon" && (
              <span className="text-xs text-amber-400">
                Coming soon
              </span>
            )}
          </div>
        </div>
      </Card>

      {/* Logs */}
      <Card>
        <SectionHeader icon={<FileText className="h-4 w-4" />} title="Logs" />
        <div className="bg-black/30 rounded-xl p-3 font-mono text-xs text-[#8E8E93]">
          <p>Check the <code className="text-[#007AFF]">data/logs/</code> directory for full logs.</p>
          <p className="mt-1">
            Application logs: <code className="text-[#007AFF]">data/logs/jobbot.log</code>
          </p>
        </div>
      </Card>

      {/* Sticky Save Button */}
      <div className="fixed bottom-4 right-6 z-10">
        <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}>
          <Button
            size="lg"
            loading={saving}
            onClick={handleSave}
            className="shadow-lg shadow-[#007AFF]/20"
          >
            {saved ? (
              <>
                <CheckCircle2 className="h-4 w-4" />
                Saved
              </>
            ) : (
              <>
                <Save className="h-4 w-4" />
                Save Settings
              </>
            )}
          </Button>
        </motion.div>
      </div>

      <AnimatePresence>
        {showAddSource && (
          <AddSourceForm
            onClose={() => setShowAddSource(false)}
            onAdd={handleAddSource}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
