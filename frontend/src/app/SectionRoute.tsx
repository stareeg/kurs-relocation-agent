import type { ReactNode } from "react"
import { NotFound } from "@/app/NotFound"
import { useAuthStatusQuery } from "@/features/auth/use-auth-status"
import { isSectionVisible, type UiSection } from "@/features/auth/sections"

/** Маршрут раздела, скрытого флагом (U-0): вместо страницы — «страницы нет». */
export function SectionRoute({ section, children }: { section: UiSection; children: ReactNode }) {
  const { data } = useAuthStatusQuery()
  if (!isSectionVisible(data, section)) return <NotFound />
  return <>{children}</>
}
