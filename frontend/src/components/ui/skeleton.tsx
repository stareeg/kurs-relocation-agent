import * as React from "react"

import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-lg bg-muted", className)}
      {...props}
    />
  )
}

// Карточка/панель-плейсхолдер (JobCard, OfferCard, PrepPackCard и т.п.) — прямоугольный блок.
function SkeletonCard({ className, ...props }: React.ComponentProps<"div">) {
  return <Skeleton className={cn("h-24 w-full rounded-xl", className)} {...props} />
}

// Одна или несколько строк текста убывающей ширины (заголовок карточки, абзац, метаданные).
function SkeletonRow({
  lines = 1,
  className,
  lineClassName,
}: {
  lines?: number
  className?: string
  lineClassName?: string
}) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-4", i === lines - 1 && lines > 1 ? "w-4/5" : "w-full", lineClassName)}
        />
      ))}
    </div>
  )
}

// Горизонтальная рельса карточек (VacancyCardRail, карусель вопросов, колонки офферов).
function SkeletonRail({
  count = 3,
  className,
  itemClassName,
}: {
  count?: number
  className?: string
  itemClassName?: string
}) {
  return (
    <div className={cn("flex gap-4 overflow-hidden", className)}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className={cn("h-24 w-52 shrink-0 rounded-xl", itemClassName)} />
      ))}
    </div>
  )
}

export { Skeleton, SkeletonCard, SkeletonRow, SkeletonRail }
