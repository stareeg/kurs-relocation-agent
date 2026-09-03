import { QueryClient } from "@tanstack/react-query"
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister"
import {
  removeOldestQuery,
  type PersistQueryClientOptions,
} from "@tanstack/react-query-persist-client"

// Единый клиент кэша (ux_plan.md, раздел 2.3). Дефолты консервативные;
// staleTime на раздел уточняется в хуках queries/*.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
})

// P-10: мгновенный первый экран после перезапуска браузера, обновление — в фоне (staleTime выше
// всё равно триггерит refetch). Поднять версию при несовместимой смене формы данных в query-функциях
// — иначе чужой persisted-кэш в localStorage гидратируется как валидный и ломает рендер.
// 2026-08-26: 1 → 2 — career/timeline сменил форму на useInfiniteQuery без бампа, старый
// плоский кэш ломал InfiniteQueryObserver на `state.data.pages.length` (крашил «Карьеру»).
const PERSIST_CACHE_VERSION = "2"

export const queryPersister = createAsyncStoragePersister({
  // Safari private mode throws on localStorage — без обёртки персист валит гидратацию.
  storage: {
    getItem: (key) => {
      try {
        return Promise.resolve(window.localStorage.getItem(key))
      } catch {
        return Promise.resolve(null)
      }
    },
    setItem: (key, value) => {
      try {
        window.localStorage.setItem(key, value)
      } catch {
        /* quota / private mode */
      }
      return Promise.resolve()
    },
    removeItem: (key) => {
      try {
        window.localStorage.removeItem(key)
      } catch {
        /* ignore */
      }
      return Promise.resolve()
    },
  },
  key: "cc-query-cache",
  // Рекомендованный паттерн библиотеки на переполнение квоты localStorage: не терять весь
  // персист молча, а вытеснять самый старый запрос и повторить попытку записи.
  retry: removeOldestQuery,
})

// Ключи, которые держат клиентскую эфемериду, а не серверные данные: персистить их нечего.
// `resume/search-profile/suggest` — слайт подсказок «Приоритеты»: он нужен только чтобы выжить
// размонтирование панели, а сутки спустя подсказка по типу роли/отрасли всплыла бы вне контекста.
const EPHEMERAL_QUERY_KEYS: readonly string[] = ["resume/search-profile/suggest"]

function isEphemeral(queryKey: readonly unknown[]): boolean {
  return EPHEMERAL_QUERY_KEYS.includes(queryKey.join("/"))
}

export const queryPersistOptions: Omit<PersistQueryClientOptions, "queryClient"> = {
  persister: queryPersister,
  maxAge: 24 * 60 * 60 * 1000,
  buster: PERSIST_CACHE_VERSION,
  dehydrateOptions: {
    // Дефолт библиотеки — только успешные запросы; сохраняем его и отсекаем эфемериду.
    shouldDehydrateQuery: (query) =>
      query.state.status === "success" && !isEphemeral(query.queryKey),
  },
}
