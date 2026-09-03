// Черновик формы + свежие данные с бэкенда → черновик, в котором чужие правки применены, а
// несохранённый ввод владельца уцелел.
//
// Зачем: экран «Резюме» правится из двух мест сразу — форма справа копит черновик до кнопки
// «Сохранить», а панель слева (вилка, налоги, роль) пишет на бэкенд сразу. Форма
// сравнивала черновик с живыми данными query, поэтому автосейв из панели делал её «грязной», а
// «Сохранить» PUT-ил устаревшие поля поверх только что сохранённых — выбор откатывался к
// дефолту. Правильный ответ — не запрещать одно из двух, а пересаживать черновик на новую базу.

/** Дефолтное сравнение: структурное, без ссылочной идентичности. */
function deepEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

export interface RebaseOptions<T> {
  /** Ключи-объекты, которые сливаются по под-ключам: правка `position.title` в форме не должна
   * мешать автосейву `position.salary_basis` из другой панели приехать в черновик. */
  nestedKeys?: readonly (keyof T & string)[]
  /** Нормализация значения перед сравнением — снять клиентские поля (`_uid` строк формы). */
  normalize?: (value: unknown) => unknown
}

function rebaseFlat<T extends object>(
  draft: T,
  prev: T,
  next: T,
  eq: (a: unknown, b: unknown) => boolean,
): T {
  const draftRec = draft as Record<string, unknown>
  const prevRec = prev as Record<string, unknown>
  let changed = false
  const out = { ...draft } as Record<string, unknown>
  for (const [key, value] of Object.entries(next as Record<string, unknown>)) {
    // Под-поле, которого владелец не касался, берём с бэкенда; отредактированное — не трогаем.
    if (eq(draftRec[key], prevRec[key]) && !eq(draftRec[key], value)) {
      out[key] = value
      changed = true
    }
  }
  return (changed ? out : draft) as T
}

/**
 * `prev` — данные, из которых вырос `draft` (база черновика). Поле берётся из `next`, только
 * если владелец его не менял относительно базы; иначе побеждает черновик.
 *
 * Если менять нечего — возвращает исходный `draft` (тот же объект), чтобы мемоизированные
 * секции формы резюме не ре-рендерились от эха собственного PATCH.
 */
export function rebaseDraft<T extends object>(
  draft: T,
  prev: T,
  next: T,
  { nestedKeys = [], normalize }: RebaseOptions<T> = {},
): T {
  const eq = normalize
    ? (a: unknown, b: unknown) => deepEqual(normalize(a), normalize(b))
    : deepEqual
  const draftRec = draft as Record<string, unknown>
  const prevRec = prev as Record<string, unknown>
  const nested = new Set<string>(nestedKeys as readonly string[])
  let changed = false
  const out = { ...draft } as Record<string, unknown>

  for (const [key, value] of Object.entries(next as Record<string, unknown>)) {
    if (nested.has(key)) {
      const merged = rebaseFlat(draftRec[key] as object, prevRec[key] as object, value as object, eq)
      if (merged !== draftRec[key]) {
        out[key] = merged
        changed = true
      }
      continue
    }
    // Списки строк формы несут клиентские `_uid`: если по сути ничего не поменялось, оставляем
    // черновик как есть — иначе строки перемонтируются и теряют фокус ввода.
    if (eq(draftRec[key], value)) continue
    if (eq(draftRec[key], prevRec[key])) {
      out[key] = value
      changed = true
    }
  }
  return changed ? (out as T) : draft
}
