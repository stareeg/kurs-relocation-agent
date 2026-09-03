import { useCallback, useSyncExternalStore } from "react"

import { markTipShown, ONBOARDING_SEEN_MS, wasTipShownRecently } from "@/lib/tip-memory"

/** Legacy-ключ одноразового dismiss (до tip-memory). Читаем оба. */
export const hintDismissedKey = (id: string) => `copilot.hint.${id}.dismissed`

/** Канонические id одноразовых онбординг-подсказок. */
export const ONBOARDING_HINT_IDS = {
  jobsExtension: "jobs.extension",
  resumeSearchCriteria: "resume.search-criteria",
  chatTelegramPaste: "chat.telegram-paste",
  /** Первая вакансия в воронке: клик по карточке открывает разбор. */
  jobsFirstCard: "jobs.first-card",
  /** Первый готовый балл резюме на правой панели. */
  resumeScoreReady: "resume.score-ready",
  /** Пустая вкладка «Офферы»: откуда они появляются. */
  offersEmpty: "offers.empty",
  /** Первый запуск: куда вставить ключ OpenRouter. */
  settingsPasteKey: "settings.paste-key",
  /** После сохранения ключа: перейти в Резюме. */
  settingsAfterKeyResume: "settings.after-key-resume",
  /** На вкладке Резюме: заполнить критерии и опыт. */
  resumeFillBasics: "resume.fill-basics",
} as const

export type OnboardingHintId = (typeof ONBOARDING_HINT_IDS)[keyof typeof ONBOARDING_HINT_IDS]

function readBool(key: string, defaultValue: boolean): boolean {
  try {
    const raw = localStorage.getItem(key)
    if (raw != null) return raw === "1"
  } catch {
    /* ignore */
  }
  return defaultValue
}

function writeBool(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? "1" : "0")
  } catch {
    /* ignore */
  }
}

let epoch = 0
const listeners = new Set<() => void>()

function subscribe(cb: () => void) {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

function getSnapshot() {
  return epoch
}

function bump() {
  epoch += 1
  listeners.forEach((cb) => cb())
}

function isLegacyDismissed(id: string) {
  return readBool(hintDismissedKey(id), false)
}

function isHintSeen(id: string) {
  if (isLegacyDismissed(id)) return true
  return wasTipShownRecently(`onboarding.${id}`, ONBOARDING_SEEN_MS)
}

/**
 * Одноразовые OnboardingHint (ключ → резюме и т.п.).
 * Показ = «уже видели»: не повторяем при возврате на экран / ремаунте.
 * Цепочку онбординга (ключ → резюме) не режем глобальной паузой — только per-id.
 * Контекстная помощь — в «Что делать?»; точечные hover — через HelpTip.
 */
export function useOnboardingHints() {
  useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  const shouldShow = useCallback((id: string) => !isHintSeen(id), [])

  const dismissHint = useCallback((id: string) => {
    writeBool(hintDismissedKey(id), true)
    markTipShown(`onboarding.${id}`)
    bump()
  }, [])

  return {
    shouldShow,
    dismissHint,
  }
}
