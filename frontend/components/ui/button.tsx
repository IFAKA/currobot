"use client"
import { cn } from "@/lib/utils"
import { Loader2 } from "lucide-react"
import { forwardRef } from "react"

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "ghost" | "success"
  size?: "sm" | "md" | "lg"
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", loading, disabled, children, ...props }, ref) => {
    const variants = {
      default: "bg-[#007AFF] hover:bg-[#0066D6] text-white",
      destructive: "bg-[#FF3B30] hover:bg-[#D63029] text-white",
      outline: "border border-white/10 hover:bg-white/5 text-white",
      ghost: "hover:bg-white/5 text-[#8E8E93] hover:text-white",
      success: "bg-[#34C759] hover:bg-[#2DB54B] text-white",
    }
    const sizes = {
      sm: "px-3 py-1.5 text-xs rounded-lg",
      md: "px-4 py-2 text-sm rounded-xl",
      lg: "px-6 py-3 text-base rounded-xl",
    }
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          "inline-flex items-center justify-center gap-2 font-medium transition-all duration-150",
          "disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.97]",
          variants[variant], sizes[size], className
        )}
        {...props}
      >
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {children}
      </button>
    )
  }
)
Button.displayName = "Button"
