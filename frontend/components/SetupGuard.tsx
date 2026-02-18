"use client"
import { useEffect } from "react"
import { usePathname, useRouter } from "next/navigation"
import { api } from "@/lib/api"

export function SetupGuard() {
  const pathname = usePathname()
  const router = useRouter()

  useEffect(() => {
    if (pathname === "/setup") return
    api.getSetupStatus().then(status => {
      if (!status.setup_complete) {
        router.replace("/setup")
      }
    }).catch(() => {
      // Backend not ready yet — don't redirect
    })
  }, [pathname, router])

  return null
}
