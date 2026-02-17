"use client"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { LayoutGrid, Briefcase, Kanban, FileText, Settings, Bot } from "lucide-react"
import { cn } from "@/lib/utils"
import { motion } from "motion/react"

const nav = [
  { href: "/",             icon: LayoutGrid,   label: "Dashboard" },
  { href: "/jobs",         icon: Briefcase,    label: "Jobs" },
  { href: "/applications", icon: Kanban,       label: "Applications" },
  { href: "/cv",           icon: FileText,     label: "CV Profiles" },
  { href: "/settings",     icon: Settings,     label: "Settings" },
]

export function Sidebar({ pendingCount = 0 }: { pendingCount?: number }) {
  const pathname = usePathname()
  return (
    <nav className="fixed left-0 top-0 h-full w-16 bg-[#1C1C1E] border-r border-white/5 flex flex-col items-center py-4 gap-1 z-40">
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
                  : "text-[#8E8E93] hover:text-white hover:bg-white/5"
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
