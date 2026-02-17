import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—"
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)
  if (diffMins < 1) return "ahora"
  if (diffMins < 60) return `hace ${diffMins}m`
  if (diffHours < 24) return `hace ${diffHours}h`
  if (diffDays < 7) return `hace ${diffDays}d`
  return date.toLocaleDateString("es-ES", { day: "numeric", month: "short" })
}

export function statusColor(status: string): string {
  const map: Record<string, string> = {
    applied: "text-[#34C759]",
    offered: "text-[#34C759]",
    pending_human_review: "text-amber-400",
    cv_generating: "text-[#007AFF]",
    cv_ready: "text-[#007AFF]",
    rejected: "text-[#FF3B30]",
    withdrawn: "text-[#FF3B30]",
    cv_failed_validation: "text-[#FF3B30]",
    submitted_ambiguous: "text-amber-400",
    scraped: "text-[#8E8E93]",
  }
  return map[status] ?? "text-[#8E8E93]"
}

export function statusBg(status: string): string {
  const map: Record<string, string> = {
    applied: "bg-[#34C759]/10 text-[#34C759]",
    offered: "bg-[#34C759]/10 text-[#34C759]",
    interview_scheduled: "bg-purple-500/10 text-purple-400",
    pending_human_review: "bg-amber-400/10 text-amber-400",
    cv_generating: "bg-[#007AFF]/10 text-[#007AFF]",
    cv_ready: "bg-[#007AFF]/10 text-[#007AFF]",
    rejected: "bg-[#FF3B30]/10 text-[#FF3B30]",
    cv_failed_validation: "bg-[#FF3B30]/10 text-[#FF3B30]",
    submitted_ambiguous: "bg-amber-400/10 text-amber-400",
    scraped: "bg-white/5 text-[#8E8E93]",
    qualified: "bg-white/5 text-[#8E8E93]",
  }
  return map[status] ?? "bg-white/5 text-[#8E8E93]"
}

export function cvProfileLabel(profile: string): string {
  const map: Record<string, string> = {
    cashier: "Cajero/a",
    stocker: "Reponedor/a",
    logistics: "Logística",
    frontend_dev: "Frontend Dev",
    fullstack_dev: "Fullstack Dev",
  }
  return map[profile] ?? profile
}

export function cvProfileColor(profile: string): string {
  const map: Record<string, string> = {
    cashier: "bg-orange-500/10 text-orange-400",
    stocker: "bg-yellow-500/10 text-yellow-400",
    logistics: "bg-green-500/10 text-green-400",
    frontend_dev: "bg-[#007AFF]/10 text-[#007AFF]",
    fullstack_dev: "bg-purple-500/10 text-purple-400",
  }
  return map[profile] ?? "bg-white/5 text-[#8E8E93]"
}
