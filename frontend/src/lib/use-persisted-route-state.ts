import { useCallback, useReducer } from "react"
import { useSearchParams } from "react-router-dom"

function readSession(key: string): string | null {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function writeSession(key: string, value: string | null) {
  try {
    if (value == null) sessionStorage.removeItem(key)
    else sessionStorage.setItem(key, value)
  } catch {
    /* приватный режим/квота — деградируем без персиста */
  }
}

// react-router отдаёт в функциональный `setSearchParams` снимок параметров с последнего
// рендера, а не результат предыдущего вызова в том же обработчике. Поэтому два хука, которые
// правят свои параметры один за другим (ChatPage: «Сегодня» = снять и `vacancy`, и `panel`),
// затирали правку друг друга — второй вызов воскрешал параметр, снятый первым, и клик по
// «Сегодня»/контексту не уводил из диалога вакансии.
//
// Копим правки одного обработчика в общем буфере и каждый раз применяем его целиком. Буфер
// сам протухает: он привязан к снимку строки запроса, из которого начался (`base`), — как
// только React закоммитил навигацию и снимок сменился, следующий `set` начинает с чистого
// листа. Роутер в приложении один, поэтому один модульный буфер корректен.
let pendingPatch: { base: string; params: URLSearchParams } | null = null

function patchSearchParams(
  snapshot: URLSearchParams,
  param: string,
  value: string | null,
): URLSearchParams {
  const base = snapshot.toString()
  if (pendingPatch == null || pendingPatch.base !== base) {
    pendingPatch = { base, params: new URLSearchParams(snapshot) }
  }
  if (value == null) pendingPatch.params.delete(param)
  else pendingPatch.params.set(param, value)
  return new URLSearchParams(pendingPatch.params)
}

interface PersistedRouteStateOptions<T extends string> {
  /** Имя URL search-параметра — источник истины для «выбора» (что открыто на экране):
   * ссылка с этим параметром всегда побеждает, переживает F5, видна в devtools. Опусти
   * для «вида/раскладки» (доска/список и т.п.) — тем в URL не место, они не то, чем
   * делятся по ссылке. */
  param?: string
  /** Ключ sessionStorage вкладки: фолбэк для `param`, пока в URL параметра нет (переход
   * между разделами без явного выбора), либо единственный носитель для вида/раскладки. */
  storageKey: string
  fallback?: T | null
}

/**
 * Замена модульным синглтонам (`features/jobs/selected-vacancy.ts`, `persistedView` в
 * JobsWorkspace, `persistedSelection` в ChatPage) — те не переживали F5, не шарились
 * ссылкой и были не видны в devtools (F-09).
 *
 * Читаем `sessionStorage` напрямую при каждом рендере, а не кэшируем в `useState` (правка
 * 2026-08-11): компонент, смонтированный один раз на всё приложение (`AppShell` — бейдж «Шанс
 * оффера» в меню слева, через `useMarketRange`), иначе застревал бы со значением на момент
 * своего монтирования и не видел бы правки, сделанные другим инстансом этого хука в другом
 * месте дерева (например, шкалой периода на самой «Рынке») — баг «бейдж скачет и не совпадает
 * с графиком при уходе с раздела». `useSearchParams` уже переподключает компонент на каждую
 * навигацию (location меняет identity), так что свежее чтение подхватывается само; для формы
 * без `param` (вид/раскладка, где навигации не происходит) `set()` форсирует лишний рендер сам.
 */
export function usePersistedRouteState<T extends string>({
  param,
  storageKey,
  fallback = null,
}: PersistedRouteStateOptions<T>): [T | null, (value: T | null) => void] {
  const [searchParams, setSearchParams] = useSearchParams()
  const [, forceUpdate] = useReducer((c: number) => c + 1, 0)

  const urlValue = param ? (searchParams.get(param) as T | null) : null
  const sessionValue = (readSession(storageKey) as T | null) ?? fallback
  const value = param ? (urlValue ?? sessionValue) : sessionValue

  const set = useCallback(
    (next: T | null) => {
      writeSession(storageKey, next)
      if (param) {
        setSearchParams((prev) => patchSearchParams(prev, param, next), { replace: true })
      } else {
        forceUpdate()
      }
    },
    [param, storageKey, setSearchParams],
  )

  return [value, set]
}
