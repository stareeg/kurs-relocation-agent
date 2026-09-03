/**
 * Сон, переживающий усыпление MV3 service worker'а.
 *
 * Баг (прод, до 2026-08-31): оба раннера спали голым `setTimeout` — автоотклики между
 * кандидатами 2–5 мин (`auto_apply_delay_ms`) и до 2 мин перед реальной отправкой
 * (`auto_apply_min_real_interval_ms`), автопросмотр — джиттер до 60 с (`discovery_delay_ms`).
 * MV3 гасит service worker после ~30 с БЕЗДЕЙСТВИЯ, а висящий `setTimeout` бездействием
 * считается: воркер умирал во сне, промис не резолвился никогда, остаток тика (следующие
 * кандидаты, второй проход, heartbeat) просто не выполнялся.
 *
 * В журнале это выглядело так, что тика с работой не бывает вовсе: за 4 дня в проде — только
 * строки «кандидатов=0» (единственный путь БЕЗ снов), ни одной с `кандидатов>0`. Ровно
 * поэтому «раннер вроде живой, а откликов нет».
 *
 * Фикс: пока спим, дёргаем дешёвый `chrome.*` API раз в `PING_INTERVAL_MS` — вызов
 * extension-API сбрасывает idle-таймер воркера, и сон досыпает до конца.
 */

/** Заметно меньше 30-секундного idle-таймера MV3 — с запасом на занятый воркер. */
const PING_INTERVAL_MS = 20_000

/** Ниже этого порога пинговать незачем: воркер и так не успеет уснуть. */
const PING_THRESHOLD_MS = 15_000

/** Дешёвый вызов extension-API — единственная его задача сбросить idle-таймер воркера. */
function pingServiceWorker(): void {
  try {
    chrome.runtime.getPlatformInfo(() => {
      // Ошибка пинга ничего не значит для сна — читаем lastError, чтобы chrome не ругался.
      void chrome.runtime.lastError
    })
  } catch {
    /* воркер уже гасится — сон всё равно доспит или прервётся вместе с ним */
  }
}

/**
 * `await keepAliveSleep(ms)` вместо `setTimeout`-промиса везде, где сон может превысить
 * ~15 с. Короткие сны (стаггер вкладок, ретраи) идут обычным путём — лишние пинги там
 * только шумят.
 */
export function keepAliveSleep(ms: number): Promise<void> {
  if (!(ms > 0)) return Promise.resolve()
  return new Promise((resolve) => {
    if (ms < PING_THRESHOLD_MS) {
      setTimeout(resolve, ms)
      return
    }
    const ping = setInterval(pingServiceWorker, PING_INTERVAL_MS)
    setTimeout(() => {
      clearInterval(ping)
      resolve()
    }, ms)
  })
}

export const _PING_INTERVAL_MS_FOR_TESTS = PING_INTERVAL_MS
export const _PING_THRESHOLD_MS_FOR_TESTS = PING_THRESHOLD_MS
