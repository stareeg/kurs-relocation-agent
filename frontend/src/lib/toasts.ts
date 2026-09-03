/** Общие формулировки тостов (FR2-84/85): без жаргона, с действием где уместно. */

import { downloadLogsBundle } from "@/api/logs"
import { toast } from "sonner"

export const OPENROUTER_MISSING_TOAST =
  "Нет ключа OpenRouter или исчерпан лимит — вкладка «Аккаунт»"

/** Общий id тоста серьёзной ошибки запроса — повторный сбой обновляет один тост на месте,
 * не плодит стопку одинаковых. */
const SERIOUS_ERROR_TOAST_ID = "api-serious-error"

/**
 * Тост серьёзной ошибки запроса (5xx / сеть / таймаут — «LLM недоступна» тоже сюда, это 503)
 * с действием «Скачать логи». Раньше кнопка жила только внизу «Параметров», тост всплывал и
 * гасал за несколько секунд — архивы приходили редко и поздно.
 *
 * Скачивание стартует в том же синхронном стеке, что и клик: иначе браузер не считает
 * `a.download` пользовательским жестом (динамический `import()` рвал цепочку — кнопка
 * молчала). Цикл `client → toasts → logs → client` размыкается с той стороны: `client.ts`
 * подгружает этот модуль лениво.
 */
export function showSeriousErrorToast(message: string): void {
  toast.error(message, {
    id: SERIOUS_ERROR_TOAST_ID,
    action: {
      label: "Скачать логи",
      onClick: () => {
        void downloadLogsBundle()
      },
    },
  })
}
