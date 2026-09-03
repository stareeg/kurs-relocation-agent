import { useId } from "react"
import { cn } from "@/lib/utils"

interface LogoMarkProps {
  size?: number
  className?: string
}

export function LogoMark({ size = 24, className }: LogoMarkProps) {
  const gradientId = useId()
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      className={cn("shrink-0", className)}
      aria-hidden="true"
    >
      <rect width="40" height="40" rx="9" fill={`url(#${gradientId})`} />
      <path
        d="M10 21 L17.5 28 L28 12"
        stroke="#fff"
        strokeWidth="4.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="31" cy="9" r="3.4" fill="#fbbf24" stroke="#0f172a" strokeWidth="1.6" />
      <defs>
        <linearGradient
          id={gradientId}
          x1="0"
          y1="0"
          x2="40"
          y2="40"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#0f172a" />
          <stop offset="1" stopColor="#4338ca" />
        </linearGradient>
      </defs>
    </svg>
  )
}

interface LogoProps {
  size?: number
  className?: string
  textClassName?: string
}

export function Logo({ size = 22, className, textClassName }: LogoProps) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-2", className)}>
      <LogoMark size={size} />
      <span className={cn("truncate font-semibold tracking-tight text-slate-900", textClassName)}>
        VACMatch
      </span>
    </span>
  )
}
