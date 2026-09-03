"use client"

import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react"
import { Toaster as Sonner, type ToasterProps } from "sonner"

/** Длительность появления тоста = motion-rise (180 мс), не дефолтные 400. */
const TOAST_MOTION_MS = 180

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="light"
      position="bottom-right"
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
          // Sonner читает длительность перехода через inline transition; дублируем в CSS-переменной
          // и жёстко в globals (см. [data-sonner-toast]).
          "--toast-animation-duration": `${TOAST_MOTION_MS}ms`,
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
