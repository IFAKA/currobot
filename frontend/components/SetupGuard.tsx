"use client"
import { useEffect, useRef } from "react"
import { usePathname, useRouter } from "next/navigation"
import { api } from "@/lib/api"

export function SetupGuard() {
  const pathname = usePathname()
  const router = useRouter()
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (pathname === "/setup") return

    const check = () => {
      api.getSetupStatus().then(status => {
        if (!status.setup_complete) {
          router.replace("/setup")
        }
      }).catch(() => {
        // Backend not ready yet — retry after 1s
        retryRef.current = setTimeout(check, 1000)
      })
    }

    check()

    return () => {
      if (retryRef.current) clearTimeout(retryRef.current)
    }
  }, [pathname, router])

  return null
}
