import { cn } from "@/lib/utils"

type DotStatus = "ok" | "warning" | "error" | "unknown" | "running"

interface HealthDotProps { status: DotStatus; className?: string; pulse?: boolean }

export function HealthDot({ status, className, pulse = false }: HealthDotProps) {
  const colors: Record<DotStatus, string> = {
    ok: "bg-[#34C759]",
    running: "bg-[#007AFF]",
    warning: "bg-amber-400",
    error: "bg-[#FF3B30]",
    unknown: "bg-[#8E8E93]",
  }
  return (
    <span className={cn("relative inline-flex h-2 w-2", className)}>
      {pulse && (
        <span className={cn(
          "animate-ping absolute inline-flex h-full w-full rounded-full opacity-75",
          colors[status]
        )} />
      )}
      <span className={cn("relative inline-flex rounded-full h-2 w-2", colors[status])} />
    </span>
  )
}
