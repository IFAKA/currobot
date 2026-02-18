import { cn } from "@/lib/utils"

interface CardProps { children: React.ReactNode; className?: string; onClick?: () => void }

export function Card({ children, className, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "backdrop-blur-sm rounded-2xl p-4 border transition-colors",
        onClick && "cursor-pointer",
        className
      )}
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      {children}
    </div>
  )
}

export function CardHeader({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("mb-3", className)}>{children}</div>
}

export function CardTitle({ children, className }: { children: React.ReactNode; className?: string }) {
  return <h3 className={cn("text-sm font-semibold text-[var(--fg)]", className)}>{children}</h3>
}
