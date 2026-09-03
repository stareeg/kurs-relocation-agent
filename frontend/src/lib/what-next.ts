/**
 * Детерминированная подсказка «Что делать?»: последнее действие + следующий шаг.
 * Без LLM, без «срочных дел в Сегодня».
 */
import {
  WHAT_NEXT_LAST,
  WHAT_NEXT_NEXT,
  type WhatNextLastId,
  type WhatNextNextId,
} from "@/lib/what-next-cards"

export type WhatNextBlock = {
  title: string
  body: string
  href?: string
  cta?: string
}

/** Готовая подсказка для панели «Что делать?». */
export type WhatNextGuidance = {
  last: WhatNextBlock
  next: WhatNextBlock
}

export type WhatNextContext = {
  pathname: string
  hasOpenRouterKey: boolean
  /** Критерии/резюме достаточно заполнены для осмысленной оценки. */
  resumeReady: boolean
  activeJobsCount: number
  activeChatsCount: number
  offersCount: number
  /** На экране список отфильтрован «в ноль», при этом вакансии в воронке есть. */
  jobsFilteredEmpty?: boolean
  /** На скринингах/техничках выбрана вакансия. */
  hasSelectedVacancy?: boolean
}

function routeBase(pathname: string): string {
  if (pathname.startsWith("/jobs")) return "/jobs"
  if (pathname.startsWith("/admin")) return "/admin"
  return pathname.replace(/\/$/, "") || "/"
}

function lastIdFor(pathname: string): WhatNextLastId {
  if (pathname.includes("/jobs/") && pathname !== "/jobs") return "jobsDrawer"
  const base = routeBase(pathname)
  const map: Record<string, WhatNextLastId> = {
    "/jobs": "jobs",
    "/chat": "chat",
    "/screening": "screening",
    "/tech": "tech",
    "/offers": "offers",
    "/market": "market",
    "/companies": "companies",
    "/resume": "resume",
    "/career": "career",
    "/extension": "extension",
    "/settings": "settings",
    "/admin": "admin",
  }
  return map[base] ?? "unknown"
}

function blockLast(id: WhatNextLastId): WhatNextBlock {
  const copy = WHAT_NEXT_LAST[id]
  return { title: copy.title, body: copy.body }
}

function blockNext(id: WhatNextNextId, href?: string): WhatNextBlock {
  const copy = WHAT_NEXT_NEXT[id]
  return {
    title: copy.title,
    body: copy.body,
    href,
    cta: "cta" in copy ? copy.cta : undefined,
  }
}

export function buildWhatNextGuidance(ctx: WhatNextContext): WhatNextGuidance {
  const base = routeBase(ctx.pathname)
  const last = blockLast(lastIdFor(ctx.pathname))

  // Блокеры онбординга важнее экранных советов.
  if (!ctx.hasOpenRouterKey) {
    return { last, next: blockNext("needKey", "/settings") }
  }
  if (!ctx.resumeReady) {
    return { last, next: blockNext("needResume", "/resume") }
  }
  if (ctx.activeJobsCount === 0 && base !== "/extension") {
    return { last, next: blockNext("needExtension", "/extension") }
  }

  if (base === "/jobs") {
    if (ctx.jobsFilteredEmpty) return { last, next: blockNext("jobsEmptyFilter") }
    if (ctx.pathname.includes("/jobs/") && ctx.pathname !== "/jobs") {
      return { last, next: blockNext("jobsScoreMore") }
    }
    return { last, next: blockNext("jobsOpenCard") }
  }

  if (base === "/chat") {
    if (ctx.activeChatsCount === 0) {
      return { last, next: blockNext("chatEmpty", "/extension") }
    }
    return { last, next: blockNext("chatReply") }
  }

  if (base === "/screening") {
    if (!ctx.hasSelectedVacancy) return { last, next: blockNext("screeningPick") }
    return { last, next: blockNext("screeningPack") }
  }

  if (base === "/tech") {
    if (!ctx.hasSelectedVacancy) return { last, next: blockNext("techPick") }
    return { last, next: blockNext("techPrep") }
  }

  if (base === "/offers") {
    if (ctx.offersCount === 0) return { last, next: blockNext("offersEmpty") }
    return { last, next: blockNext("offersCompare") }
  }

  if (base === "/market") {
    if (ctx.activeJobsCount < 8) {
      return { last, next: blockNext("marketThin", "/jobs") }
    }
    return { last, next: blockNext("marketRead") }
  }

  if (base === "/companies") return { last, next: blockNext("companiesSort") }
  if (base === "/resume") return { last, next: blockNext("resumeFill") }
  if (base === "/career") return { last, next: blockNext("careerUpdate") }
  if (base === "/extension") return { last, next: blockNext("extensionInstall") }
  if (base === "/settings") {
    return { last, next: blockNext("settingsDone", "/resume") }
  }

  return { last, next: blockNext("fallback") }
}

/** Подпись раздела для шапки панели. */
export function screenLabel(pathname: string): string {
  const base = routeBase(pathname)
  const labels: Record<string, string> = {
    "/resume": "Резюме",
    "/chat": "Чаты",
    "/jobs": "Вакансии",
    "/screening": "Скрининги",
    "/tech": "Технички",
    "/offers": "Офферы",
    "/market": "Рынок",
    "/companies": "Компании",
    "/career": "Карьера",
    "/extension": "Автоотклики",
    "/settings": "Аккаунт",
    "/admin": "Админ",
  }
  return labels[base] ?? "этот экран"
}
