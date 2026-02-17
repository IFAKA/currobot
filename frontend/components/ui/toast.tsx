"use client"
import { useEffect, useState } from "react"
import { motion, AnimatePresence } from "motion/react"
import { XCircle, CheckCircle2, Info } from "lucide-react"
import { toast } from "@/lib/toast"
import { cn } from "@/lib/utils"

interface ToastItem {
  id: number
  msg: string
  type: "error" | "success" | "info"
}

let _nextId = 0

export function Toaster() {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  useEffect(() => {
    toast._register((msg, type) => {
      const id = _nextId++
      setToasts(prev => [...prev, { id, msg, type }])
      setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000)
    })
    return () => toast._unregister()
  }, [])

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 items-end pointer-events-none">
      <AnimatePresence>
        {toasts.map(t => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, x: 40, scale: 0.95 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 40, scale: 0.95 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            className={cn(
              "flex items-center gap-2.5 px-4 py-3 rounded-2xl text-sm font-medium shadow-xl pointer-events-auto max-w-sm",
              t.type === "error"   && "bg-[#FF3B30]/10 border border-[#FF3B30]/20 text-[#FF3B30]",
              t.type === "success" && "bg-[#34C759]/10 border border-[#34C759]/20 text-[#34C759]",
              t.type === "info"    && "bg-white/5 border border-white/10 text-white",
            )}
          >
            {t.type === "error"   && <XCircle      className="h-4 w-4 shrink-0" />}
            {t.type === "success" && <CheckCircle2 className="h-4 w-4 shrink-0" />}
            {t.type === "info"    && <Info         className="h-4 w-4 shrink-0" />}
            {t.msg}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
