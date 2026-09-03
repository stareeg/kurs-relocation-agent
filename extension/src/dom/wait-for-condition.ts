/**
 * EXT-F3: общий helper вместо fixed-interval поллинга (300мс) для ожидания SPA-догрузки блока
 * статистики. MutationObserver резолвит промис сразу на реальном DOM-изменении (не ждёт следующий
 * poll-тик) и дешевле дёргает `check` (только на мутациях, а не по таймеру). Дедлайн остаётся
 * safety net'ом на случай, если виджет вообще не появится (или мутации не фиксируют изменение).
 */

type WaitForConditionOptions<T> = {
  /** Максимальное время ожидания, мс. */
  timeoutMs?: number
  /** Узел, за которым наблюдаем (по умолчанию document.body). */
  target?: Node
  observerOptions?: MutationObserverInit
  /** true — немедленно резолвить null (страница сменилась/расширение перезагружено). */
  shouldCancel?: () => boolean
  /** Когда результат check() считать финальным (по умолчанию — просто не null). */
  isAcceptable?: (value: T | null) => boolean
}

const DEFAULT_OBSERVER_OPTIONS: MutationObserverInit = {
  childList: true,
  subtree: true,
  characterData: true,
}

/** Резолвится значением check(), как только оно станет isAcceptable, либо по дедлайну (тогда
 *  берём последний непустой результат — свежий check() в приоритете, иначе последний увиденный). */
function waitForCondition<T>(
  check: () => T | null,
  options: WaitForConditionOptions<T> = {},
): Promise<T | null> {
  const timeoutMs = options.timeoutMs ?? 6000
  const target = options.target ?? document.body
  const shouldCancel = options.shouldCancel ?? (() => false)
  const isAcceptable = options.isAcceptable ?? ((value: T | null) => value != null)
  const observerOptions = options.observerOptions ?? DEFAULT_OBSERVER_OPTIONS

  return new Promise((resolve) => {
    let settled = false
    let lastSeen: T | null = null
    let observer: MutationObserver | null = null
    let timer: ReturnType<typeof setTimeout> | null = null

    const cleanup = () => {
      observer?.disconnect()
      if (timer) clearTimeout(timer)
    }

    const finish = (value: T | null) => {
      if (settled) return
      settled = true
      cleanup()
      resolve(value)
    }

    const attempt = (): boolean => {
      if (shouldCancel()) {
        finish(null)
        return true
      }
      const value = check()
      if (value != null) lastSeen = value
      if (isAcceptable(value)) {
        finish(value)
        return true
      }
      return false
    }

    if (attempt()) return

    observer = new MutationObserver(() => {
      attempt()
    })
    try {
      observer.observe(target, observerOptions)
    } catch {
      /* target не в документе — дедлайн ниже всё равно резолвит */
    }

    timer = setTimeout(() => {
      const value = check()
      finish(value != null ? value : lastSeen)
    }, timeoutMs)
  })
}

export { waitForCondition }
