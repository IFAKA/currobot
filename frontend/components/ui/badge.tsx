import { cn, statusBg, cvProfileColor, cvProfileLabel } from "@/lib/utils"

interface BadgeProps { status: string; className?: string }

export function StatusBadge({ status, className }: BadgeProps) {
  const label = status.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())
  return (
    <span className={cn(
      "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
      statusBg(status),
      className
    )}>
      {label}
    </span>
  )
}

interface PillProps { children: React.ReactNode; className?: string; color?: string }
export function Pill({ children, className, color }: PillProps) {
  return (
    <span className={cn(
      "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
      color ?? "bg-white/5 text-[#8E8E93]",
      className
    )}>
      {children}
    </span>
  )
}

interface ProfilePillProps { profile: string; className?: string }
export function ProfilePill({ profile, className }: ProfilePillProps) {
  return (
    <Pill color={cvProfileColor(profile)} className={className}>
      {cvProfileLabel(profile)}
    </Pill>
  )
}
