import { cn } from "@/lib/utils"

interface CardProps { children: React.ReactNode; className?: string; onClick?: () => void }

export function Card({ children, className, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "bg-white/80 dark:bg-white/5 backdrop-blur-sm",
        "border border-black/5 dark:border-white/10 rounded-2xl p-4",
        onClick && "cursor-pointer hover:bg-white/10 transition-colors",
        className
      )}
    >
      {children}
    </div>
  )
}

export function CardHeader({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("mb-3", className)}>{children}</div>
}

export function CardTitle({ children, className }: { children: React.ReactNode; className?: string }) {
  return <h3 className={cn("text-sm font-semibold text-white", className)}>{children}</h3>
}
