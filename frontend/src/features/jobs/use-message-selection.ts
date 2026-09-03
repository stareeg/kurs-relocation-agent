import { useCallback, useEffect, useRef, useState } from "react"

// Выделение сообщений в ленте диалога вакансии (копировать/удалить, план п.3): правый клик всегда
// добавляет цель в выделение и открывает контекстное меню; когда выделение уже не пусто, обычный
// клик по пузырю тоже переключает его, а протяжка (mousedown + mouseenter по другим пузырям)
// добавляет всё, через что прошёл курсор — и может начать выделение с нуля (жест однозначный, в
// отличие от одиночного клика). Синтетические записи ленты (звонок) и ещё не сохранённый
// оптимистичный обмен исключены вызывающей стороной — у них нет стабильного id сообщения.
//
// Клик и протяжка развязаны через ОДИН обработчик `mouseup` на window (не per-bubble onClick):
// native-порядок событий (mouseup на window раньше synthetic click на элементе) иначе бьёт по
// флагу «была ли протяжка» между handler'ами. mousedown запоминает якорь и не трогает выделение
// сразу — только mouseup решает, был это клик (переключить якорь, если уже что-то выделено) или
// протяжка (довыделить якорь к тому, что уже добавил mouseenter).

/** Переключить id в множестве — новый Set (иммутабельно, для React state). */
export function toggleSelected(ids: ReadonlySet<number>, id: number): Set<number> {
  const next = new Set(ids)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

/** Добавить id, если его ещё нет — тот же Set, если добавлять нечего (не дёргает рендер зря). */
export function withSelected(ids: ReadonlySet<number>, id: number): Set<number> {
  if (ids.has(id)) return ids as Set<number>
  const next = new Set(ids)
  next.add(id)
  return next
}

export function useMessageSelection() {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set())
  const draggingRef = useRef(false)
  const movedRef = useRef(false)
  const anchorRef = useRef<number | null>(null)

  const clear = useCallback(
    () => setSelectedIds((prev) => (prev.size === 0 ? prev : new Set())),
    [],
  )

  /** Правый клик — цель всегда попадает в выделение (не переключается). */
  const ensureSelected = useCallback((id: number) => {
    setSelectedIds((prev) => withSelected(prev, id))
  }, [])

  /** Начало возможного жеста (только ЛКМ) — само выделение не трогаем, решаем на mouseup. */
  const startPress = useCallback((id: number) => {
    draggingRef.current = true
    movedRef.current = false
    anchorRef.current = id
  }, [])

  /** Курсор зашёл на другой пузырь во время протяжки — добавляем его. */
  const enterDrag = useCallback((id: number) => {
    if (!draggingRef.current) return
    movedRef.current = true
    setSelectedIds((prev) => withSelected(prev, id))
  }, [])

  useEffect(() => {
    const onMouseUp = () => {
      const wasPressing = draggingRef.current
      const moved = movedRef.current
      const anchor = anchorRef.current
      draggingRef.current = false
      movedRef.current = false
      anchorRef.current = null
      if (!wasPressing || anchor == null) return
      if (moved) {
        // Протяжка — довыделяем стартовый пузырь (мимо него mouseenter не проходил).
        setSelectedIds((prev) => withSelected(prev, anchor))
      } else {
        // Одиночный клик — переключает якорь, но только когда выделение уже активно (иначе
        // обычное чтение ленты не должно ничего выделять).
        setSelectedIds((prev) => (prev.size > 0 ? toggleSelected(prev, anchor) : prev))
      }
    }
    window.addEventListener("mouseup", onMouseUp)
    return () => window.removeEventListener("mouseup", onMouseUp)
  }, [])

  return {
    selectedIds,
    isSelecting: selectedIds.size > 0,
    clear,
    ensureSelected,
    startPress,
    enterDrag,
  }
}

export type MessageSelection = ReturnType<typeof useMessageSelection>
