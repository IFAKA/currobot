"use client"
import { useEffect, useState, useRef, useCallback } from "react"
import { motion, AnimatePresence } from "motion/react"
import {
  Upload, FileText, CheckCircle2, AlertCircle,
  Settings as SettingsIcon, X, Cpu, Trash2
} from "lucide-react"
import { api } from "@/lib/api"
import type { CVSource } from "@/lib/types"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { cvProfileLabel, cvProfileColor, cn } from "@/lib/utils"
import Link from "next/link"

const BASE = "http://localhost:8000"

const PROFILES = [
  {
    id: "cashier",
    label: "Cajero/Dependiente",
    emoji: "🛒",
    description:
      "Reframes tech skills as customer service & POS experience. Keywords: servicio al cliente, punto de venta, atención al cliente.",
  },
  {
    id: "stocker",
    label: "Reponedor/Almacén",
    emoji: "📦",
    description:
      "Positions inventory work & organizational skills. Keywords: gestión de stock, reposición, almacén, control de inventario.",
  },
  {
    id: "logistics",
    label: "Mozo de Almacén",
    emoji: "🚚",
    description:
      "Focuses on process optimization and logistics coordination. Keywords: logística, operaciones, gestión de almacén.",
  },
  {
    id: "frontend_dev",
    label: "Frontend Developer",
    emoji: "⚛️",
    description:
      "Leads with React, Next.js, TypeScript. Highlights UI/UX, Flowence SaaS platform, responsive design.",
  },
  {
    id: "fullstack_dev",
    label: "Fullstack Developer",
    emoji: "🛠️",
    description:
      "Showcases React + Node.js + PostgreSQL + Stripe + JWT + Scandit. Full SaaS stack.",
  },
]

interface GenerateModalProps {
  profile: (typeof PROFILES)[number]
  onClose: () => void
}

function GenerateModal({ profile, onClose }: GenerateModalProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.92, opacity: 0, y: 16 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.92, opacity: 0, y: 16 }}
        transition={{ type: "spring", stiffness: 260, damping: 22 }}
        className="bg-[#2C2C2E] border border-white/10 rounded-2xl p-6 max-w-sm w-full shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="text-2xl">{profile.emoji}</span>
            <h3 className="text-base font-semibold text-white">{profile.label}</h3>
          </div>
          <button onClick={onClose} className="text-[#8E8E93] hover:text-white transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="text-sm text-[#8E8E93] mb-5">
          Generate a tailored CV for{" "}
          <span className="text-white font-medium">{profile.label}</span>? This will use Ollama
          to adapt your master CV.
        </p>

        <div className="bg-amber-400/10 border border-amber-400/20 rounded-xl px-3 py-2 mb-5 flex items-start gap-2">
          <Cpu className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-400">
            To generate a CV for a specific job, select an application from the{" "}
            <strong>Jobs page</strong> and start an application there. CV generation is triggered
            automatically per-application.
          </p>
        </div>

        <div className="flex gap-2 justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Link href="/jobs">
            <Button size="sm" onClick={onClose}>
              Go to Jobs
            </Button>
          </Link>
        </div>
      </motion.div>
    </motion.div>
  )
}

interface UploadZoneProps {
  onUpload: (source: CVSource) => void
}

function UploadZone({ onUpload }: UploadZoneProps) {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadDone, setUploadDone] = useState(false)
  const [uploadedName, setUploadedName] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [cvName, setCvName] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (file: File) => {
    if (!file.name.endsWith(".pdf")) {
      setUploadError("Please upload a PDF file")
      return
    }
    setUploading(true)
    setUploadError(null)
    try {
      const formData = new FormData()
      formData.append("file", file)
      if (cvName.trim()) formData.append("name", cvName.trim())
      const res = await fetch(`${BASE}/api/setup/upload-cv`, {
        method: "POST",
        body: formData,
      })
      if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`)
      const data = await res.json()
      setUploadDone(true)
      setUploadedName(data.name ?? file.name)
      onUpload({ id: data.id, name: data.name, filename: file.name, uploaded_at: new Date().toISOString() })
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed")
    } finally {
      setUploading(false)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  const reset = () => {
    setUploadDone(false)
    setUploadedName(null)
    setCvName("")
  }

  return (
    <div className="space-y-2">
      {!uploadDone && (
        <input
          type="text"
          placeholder="Nombre de este CV (opcional)"
          value={cvName}
          onChange={e => setCvName(e.target.value)}
          className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white placeholder:text-[#8E8E93] focus:outline-none focus:border-[#007AFF]/50"
        />
      )}
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => !uploadDone && inputRef.current?.click()}
        className={cn(
          "relative border-2 border-dashed rounded-2xl p-10 flex flex-col items-center justify-center transition-all",
          uploadDone
            ? "border-[#34C759]/40 bg-[#34C759]/5"
            : dragging
            ? "border-[#007AFF] bg-[#007AFF]/10 cursor-copy"
            : "border-white/10 hover:border-white/20 hover:bg-white/[0.03] cursor-pointer"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
        />

        {uploadDone && uploadedName ? (
          <motion.div
            initial={{ scale: 0.8 }}
            animate={{ scale: 1 }}
            transition={{ type: "spring" }}
            className="flex flex-col items-center gap-2"
          >
            <CheckCircle2 className="h-10 w-10 text-[#34C759]" />
            <p className="text-sm font-semibold text-[#34C759]">{uploadedName}</p>
            <p className="text-xs text-[#34C759]/70">uploaded successfully</p>
            <button
              onClick={e => { e.stopPropagation(); reset() }}
              className="text-xs text-[#8E8E93] hover:text-white mt-1 underline"
            >
              Upload another
            </button>
          </motion.div>
        ) : (
          <>
            <Upload className={cn("h-8 w-8 mb-3", dragging ? "text-[#007AFF]" : "text-[#8E8E93]")} />
            <p className="text-sm font-medium text-white">
              {uploading ? "Uploading..." : "Drop your CV here (PDF)"}
            </p>
            <p className="text-xs text-[#8E8E93] mt-1">or click to browse</p>
            {uploadError && (
              <p className="text-xs text-[#FF3B30] mt-2">{uploadError}</p>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default function CVProfilesPage() {
  const [profileScores, setProfileScores] = useState<Record<string, number | null>>({})
  const [cvSources, setCvSources] = useState<CVSource[]>([])
  const [profileMappings, setProfileMappings] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [selectedProfile, setSelectedProfile] = useState<(typeof PROFILES)[number] | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const [sourcesRes, appsRes, settingsRes] = await Promise.allSettled([
        api.listCVSources(),
        api.getApplications({ status: "applied" }),
        api.getSettings(),
      ])

      if (sourcesRes.status === "fulfilled") {
        setCvSources(sourcesRes.value)
      }

      if (settingsRes.status === "fulfilled") {
        const mappings: Record<string, string> = {}
        for (const profile of PROFILES) {
          const key = `cv_source_${profile.id}`
          if (settingsRes.value[key]) mappings[profile.id] = settingsRes.value[key]
        }
        setProfileMappings(mappings)
      }

      // Build best scores per profile from applied applications
      const scores: Record<string, number | null> = {}
      PROFILES.forEach(p => { scores[p.id] = null })

      if (appsRes.status === "fulfilled") {
        appsRes.value.items.forEach(a => {
          if (a.quality_score !== null) {
            const current = scores[a.cv_profile] ?? 0
            scores[a.cv_profile] = Math.max(current, a.quality_score)
          }
        })
      }

      setProfileScores(scores)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleUpload = (source: CVSource) => {
    setCvSources(prev => [source, ...prev])
  }

  const handleDelete = async (id: number) => {
    try {
      await api.deleteCVSource(id)
      setCvSources(prev => prev.filter(s => s.id !== id))
    } catch (e) {
      console.error("Failed to delete CV source", e)
    }
  }

  const handleProfileMapping = async (profileId: string, sourceId: string) => {
    setProfileMappings(prev => ({ ...prev, [profileId]: sourceId }))
    await api.updateSettings({ [`cv_source_${profileId}`]: sourceId })
  }

  const cvUploaded = cvSources.length > 0

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">CV Profiles</h1>
          <p className="text-sm text-[#8E8E93] mt-0.5">
            Manage your CVs and per-profile adaptations
          </p>
        </div>
        <Link href="/settings">
          <Button size="sm" variant="ghost">
            <SettingsIcon className="h-3.5 w-3.5" />
            Ollama Config
          </Button>
        </Link>
      </div>

      {/* CV Upload */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <FileText className="h-4 w-4 text-[#007AFF]" />
          <h2 className="text-base font-semibold text-white">Mis CVs</h2>
          <span className="text-xs text-[#8E8E93]">({cvSources.length} subidos)</span>
        </div>
        <UploadZone onUpload={handleUpload} />
        <p className="text-xs text-[#8E8E93] mt-2 px-1">
          Sube tu CV base en PDF. La IA lo adaptará para cada perfil de forma automática.
          El archivo se queda local — nunca se envía a servidores externos.
        </p>
      </div>

      {/* Uploaded CVs list */}
      {cvSources.length > 0 && (
        <div className="space-y-2">
          {cvSources.map(source => (
            <motion.div
              key={source.id}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, x: -10 }}
              className="flex items-center justify-between bg-white/5 border border-white/10 rounded-xl px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <FileText className="h-4 w-4 text-[#007AFF] shrink-0" />
                <div>
                  <p className="text-sm font-medium text-white">{source.name}</p>
                  <p className="text-xs text-[#8E8E93]">{source.filename}</p>
                </div>
              </div>
              <button
                onClick={() => handleDelete(source.id)}
                className="text-[#8E8E93] hover:text-[#FF3B30] transition-colors p-1.5 rounded-lg hover:bg-[#FF3B30]/10"
                title="Eliminar"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </motion.div>
          ))}
        </div>
      )}

      {!cvUploaded && !loading && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="bg-[#007AFF]/10 border border-[#007AFF]/20 rounded-2xl p-4 flex items-center gap-3"
        >
          <AlertCircle className="h-5 w-5 text-[#007AFF] shrink-0" />
          <div>
            <p className="text-sm font-medium text-[#007AFF]">No hay CV subido</p>
            <p className="text-xs text-[#007AFF]/70 mt-0.5">
              Sube tu CV arriba para activar la adaptación automática por perfil.
            </p>
          </div>
        </motion.div>
      )}

      {/* Profile Grid */}
      <div>
        <h2 className="text-base font-semibold text-white mb-3">Perfiles</h2>
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-48 bg-white/5 rounded-2xl animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {PROFILES.map((profile, i) => {
              const score = profileScores[profile.id] ?? null
              const assignedSourceId = profileMappings[profile.id] ?? ""
              return (
                <motion.div
                  key={profile.id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.06, type: "spring", stiffness: 180, damping: 20 }}
                  whileHover={{ y: -2 }}
                >
                  <Card
                    className="flex flex-col gap-3 h-full"
                  >
                    <div
                      className="flex items-center justify-between cursor-pointer"
                      onClick={() => setSelectedProfile(profile)}
                    >
                      <div className="flex items-center gap-2.5">
                        <span className="text-2xl">{profile.emoji}</span>
                        <div>
                          <p className="text-sm font-semibold text-white">{profile.label}</p>
                          <span className={cn(
                            "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium mt-0.5",
                            cvProfileColor(profile.id)
                          )}>
                            {cvProfileLabel(profile.id)}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5">
                        {cvUploaded ? (
                          <span className="flex items-center gap-1 text-xs text-[#34C759]">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            Ready
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-xs text-[#8E8E93]">
                            <AlertCircle className="h-3.5 w-3.5" />
                            No CV
                          </span>
                        )}
                      </div>
                    </div>

                    <p className="text-xs text-[#8E8E93] leading-relaxed">{profile.description}</p>

                    {/* CV selector for this profile */}
                    {cvSources.length > 0 && (
                      <div onClick={e => e.stopPropagation()}>
                        <select
                          value={assignedSourceId}
                          onChange={e => handleProfileMapping(profile.id, e.target.value)}
                          className="w-full bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-[#007AFF]/50 cursor-pointer"
                        >
                          <option value="">— CV automático —</option>
                          {cvSources.map(s => (
                            <option key={s.id} value={String(s.id)}>
                              {s.name}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}

                    <div className="mt-auto flex items-center justify-between pt-2 border-t border-white/5">
                      <span className="text-xs text-[#8E8E93]">
                        Last quality score:{" "}
                        {score !== null ? (
                          <span className={cn(
                            "font-semibold",
                            score >= 8 ? "text-[#34C759]" :
                            score >= 5 ? "text-amber-400" :
                            "text-[#FF3B30]"
                          )}>
                            {score}/10
                          </span>
                        ) : (
                          <span className="text-[#8E8E93]">—</span>
                        )}
                      </span>
                    </div>
                  </Card>
                </motion.div>
              )
            })}
          </div>
        )}
      </div>

      {/* Generate Modal */}
      <AnimatePresence>
        {selectedProfile && (
          <GenerateModal
            profile={selectedProfile}
            onClose={() => setSelectedProfile(null)}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
