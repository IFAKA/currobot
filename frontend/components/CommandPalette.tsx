"use client"
import { Command } from "cmdk"
import { useEffect, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { motion, AnimatePresence } from "motion/react"
import { Search, Zap, Eye, Settings, Briefcase, LayoutGrid } from "lucide-react"
import { api } from "@/lib/api"
import { playSound } from "@/lib/sounds"

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [scraperSites, setScraperSites] = useState<string[]>([])
  const router = useRouter()

  useEffect(() => {
    api.getScraperStatus()
      .then(r => setScraperSites(r.scrapers.map(s => s.site)))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen(o => !o)
        if (!open) playSound("swoosh")
      }
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("keydown", down)
    return () => document.removeEventListener("keydown", down)
  }, [open])

  const runCommand = useCallback((fn: () => void) => {
    setOpen(false)
    playSound("tick")
    fn()
  }, [])

  const scraperCommands = scraperSites.map(site => ({
    label: `Scrape ${site}`,
    icon: <Zap className="h-3.5 w-3.5" />,
    action: () => api.triggerScraper(site),
  }))

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
            onClick={() => setOpen(false)}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -8 }}
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
            className="fixed top-[20vh] left-1/2 -translate-x-1/2 w-full max-w-lg z-50"
          >
            <Command
              className="bg-[#2C2C2E] border border-white/10 rounded-2xl shadow-2xl overflow-hidden"
              shouldFilter={true}
            >
              <div className="flex items-center gap-2 px-4 py-3 border-b border-white/5">
                <Search className="h-4 w-4 text-[#8E8E93]" />
                <Command.Input
                  value={search}
                  onValueChange={setSearch}
                  placeholder="Search commands..."
                  className="flex-1 bg-transparent text-sm text-white placeholder:text-[#8E8E93] outline-none"
                />
                <kbd className="text-[10px] text-[#8E8E93] bg-white/5 px-1.5 py-0.5 rounded-md">ESC</kbd>
              </div>
              <Command.List className="max-h-72 overflow-y-auto p-2">
                <Command.Empty className="py-6 text-center text-sm text-[#8E8E93]">
                  No commands found
                </Command.Empty>

                <Command.Group heading={
                  <span className="text-[10px] text-[#8E8E93] uppercase tracking-wider px-2">Navigation</span>
                }>
                  {[
                    { label: "Dashboard",    icon: <LayoutGrid className="h-3.5 w-3.5" />, path: "/" },
                    { label: "Jobs",         icon: <Briefcase  className="h-3.5 w-3.5" />, path: "/jobs" },
                    { label: "Applications", icon: <Eye        className="h-3.5 w-3.5" />, path: "/applications" },
                    { label: "Settings",     icon: <Settings   className="h-3.5 w-3.5" />, path: "/settings" },
                  ].map(cmd => (
                    <Command.Item
                      key={cmd.path}
                      value={cmd.label}
                      onSelect={() => runCommand(() => router.push(cmd.path))}
                      className="flex items-center gap-3 px-3 py-2 rounded-xl text-sm text-white cursor-pointer
                                 aria-selected:bg-[#007AFF] aria-selected:text-white transition-colors"
                    >
                      <span className="text-[#8E8E93]">{cmd.icon}</span>
                      {cmd.label}
                    </Command.Item>
                  ))}
                </Command.Group>

                <Command.Group heading={
                  <span className="text-[10px] text-[#8E8E93] uppercase tracking-wider px-2 mt-2 block">Actions</span>
                }>
                  <Command.Item
                    value="Review next pending"
                    onSelect={() => runCommand(() => router.push("/applications?status=pending_human_review"))}
                    className="flex items-center gap-3 px-3 py-2 rounded-xl text-sm text-white cursor-pointer aria-selected:bg-[#007AFF] transition-colors"
                  >
                    <Eye className="h-3.5 w-3.5 text-[#8E8E93]" />
                    Review next pending
                  </Command.Item>
                  {scraperCommands.map(cmd => (
                    <Command.Item
                      key={cmd.label}
                      value={cmd.label}
                      onSelect={() => runCommand(() => cmd.action())}
                      className="flex items-center gap-3 px-3 py-2 rounded-xl text-sm text-white cursor-pointer aria-selected:bg-[#007AFF] transition-colors"
                    >
                      <span className="text-[#8E8E93]">{cmd.icon}</span>
                      {cmd.label}
                    </Command.Item>
                  ))}
                </Command.Group>
              </Command.List>
            </Command>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
