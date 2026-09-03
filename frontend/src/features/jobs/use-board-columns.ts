import { useCallback, useState } from "react"
import { SKIPPED_COLUMN, type BoardColumn } from "./funnel"

// Видимость колонок доски переживает уход со страницы (тот же паттерн модульного синглтона, что
// persisted-фильтры в use-job-filters.ts) — иначе скрытые колонки возвращались бы при каждом
// возврате в раздел «Вакансии». По умолчанию «Просмотр»/«Пропущено» скрыты — шумные колонки без
// сигнала для действия, пользователь возвращает их вручную через существующий UI.
let persisted = new Set<BoardColumn>(["Просмотр", SKIPPED_COLUMN])

export function useHiddenColumns() {
  const [hidden, setHidden] = useState<Set<BoardColumn>>(() => persisted)

  const hide = useCallback((col: BoardColumn) => {
    const next = new Set(persisted)
    next.add(col)
    persisted = next
    setHidden(next)
  }, [])

  const show = useCallback((col: BoardColumn) => {
    const next = new Set(persisted)
    next.delete(col)
    persisted = next
    setHidden(next)
  }, [])

  return { hidden, hide, show }
}
