import { useCallback, useEffect, useRef, useState } from "react"

/**
 * Контрол показывает `local` сразу, а родителя уведомляет с задержкой (и на blur/unmount).
 * На вкладке «Резюме» без этого каждый символ поднимает setState на всю форму — сотни
 * инпутов, авторесайз textarea и JSON-dirty — и скролл рвётся.
 *
 * `delayMs: false` — коммит только на blur/unmount (комбобоксы вроде города: живой коммит
 * закрывает саджест, роняет фокус и дёргает PATCH по всей странице).
 */
export function useBufferedValue(
  external: string,
  onCommit: (v: string) => void,
  delayMs: number | false = 300,
) {
  const [local, setLocal] = useState(external)
  const focusedRef = useRef(false)
  const onCommitRef = useRef(onCommit)
  const localRef = useRef(local)
  const externalRef = useRef(external)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    onCommitRef.current = onCommit
  }, [onCommit])
  useEffect(() => {
    localRef.current = local
  }, [local])
  useEffect(() => {
    externalRef.current = external
    if (!focusedRef.current) setLocal(external)
  }, [external])

  const flush = useCallback(() => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    const v = localRef.current
    if (v !== externalRef.current) onCommitRef.current(v)
  }, [])

  useEffect(() => () => flush(), [flush])

  const onChange = useCallback(
    (v: string) => {
      setLocal(v)
      localRef.current = v
      if (timerRef.current != null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
      if (delayMs === false) return
      timerRef.current = setTimeout(() => onCommitRef.current(v), delayMs)
    },
    [delayMs],
  )

  const onFocus = useCallback(() => {
    focusedRef.current = true
  }, [])

  const onBlur = useCallback(() => {
    focusedRef.current = false
    flush()
  }, [flush])

  const commitNow = useCallback((v: string) => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    setLocal(v)
    localRef.current = v
    onCommitRef.current(v)
  }, [])

  /** Выставить локальное значение, не коммитя (выбор из саджеста — коммит делает родитель). */
  const sync = useCallback((v: string) => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    setLocal(v)
    localRef.current = v
    externalRef.current = v
  }, [])

  return { value: local, onChange, onFocus, onBlur, commitNow, flush, sync }
}
