"use client"
import { useEffect, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { LayoutGrid, Briefcase, Kanban, FileText, Settings, Bot } from "lucide-react"
import { cn } from "@/lib/utils"
import { motion } from "motion/react"
import { api, createSSEConnection } from "@/lib/api"
import { playNotification, unlockAudio } from "@/lib/sounds"

const nav = [
  { href: "/",             icon: LayoutGrid, label: "Dashboard" },
  { href: "/jobs",         icon: Briefcase,  label: "Jobs" },
  { href: "/applications", icon: Kanban,     label: "Applications" },
  { href: "/cv",           icon: FileText,   label: "CV Profiles" },
  { href: "/settings",     icon: Settings,   label: "Settings" },
]

export function Sidebar() {
  const pathname = usePathname()
  const [pendingCount, setPendingCount] = useState(0)

  useEffect(() => {
    const handleFirstInteraction = () => {
      unlockAudio()
      document.removeEventListener("pointerdown", handleFirstInteraction)
    }
    document.addEventListener("pointerdown", handleFirstInteraction)

    const load = () => {
      api.getPendingReviews().then(r => setPendingCount(r.count)).catch(() => {})
    }
    load()
    const close = createSSEConnection((event) => {
      if (event === "review_ready") {
        playNotification()
        load()
      } else if (
        event === "application_authorized" ||
        event === "application_rejected"
      ) {
        load()
      }
    })
    return () => {
      document.removeEventListener("pointerdown", handleFirstInteraction)
      close()
    }
  }, [])

  return (
    <nav className="fixed left-0 top-0 h-full w-16 border-r flex flex-col items-center py-4 gap-1 z-40" style={{ background: "var(--bg)", borderColor: "var(--border)" }}>
      <div className="mb-4">
        <div className="w-8 h-8 rounded-xl bg-[#007AFF] flex items-center justify-center">
          <Bot className="h-4 w-4 text-white" />
        </div>
      </div>
      {nav.map(({ href, icon: Icon, label }) => {
        const active = pathname === href
        return (
          <Link key={href} href={href} title={label} className="relative">
            <motion.div
              whileTap={{ scale: 0.92 }}
              className={cn(
                "w-10 h-10 rounded-xl flex items-center justify-center transition-colors",
                active
                  ? "bg-[#007AFF] text-white"
                  : "text-[var(--fg-secondary)] hover:text-[var(--fg)] hover:bg-[var(--surface)]"
              )}
            >
              <Icon className="h-[18px] w-[18px]" />
              {href === "/applications" && pendingCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-amber-400 text-[9px] font-bold text-black flex items-center justify-center">
                  {pendingCount > 9 ? "9+" : pendingCount}
                </span>
              )}
            </motion.div>
          </Link>
        )
      })}
    </nav>
  )
}
