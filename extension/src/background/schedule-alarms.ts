/**
 * Планирование периодических `chrome.alarms` расширения (MV3).
 *
 * Баг до фикса (прод, 2026-08-27..28 — автоотклики «молчали» у активного пользователя, очередь
 * из 134 кандидатов, дневной лимит не выбран, ноль тиков раннера):
 * `background.ts` на КАЖДОМ пробуждении service worker'а звал `chrome.alarms.create(name, …)`
 * безусловно. А `chrome.alarms.create` с уже существующим именем — это «отменить и создать
 * заново»: таймер начинает отсчёт периода заново. MV3 будит воркер на каждое сообщение из
 * content-script И на каждый тик соседнего 1-минутного discovery-alarm, поэтому 5-минутный
 * `auto_apply_tick` сбрасывался чаще, чем раз в 5 минут, и НИКОГДА не доходил до срабатывания,
 * пока расширение чем-то занято. В проде это дало 2 тика автооткликов за сутки против десятков
 * тиков автопросмотра.
 *
 * Фикс: `chrome.alarms.get` → создаём, только если alarm'а нет ИЛИ его период реально
 * изменился (правка периода с сервера через рантайм-конфиг). Существующий alarm с тем же
 * периодом не трогаем — его таймер идёт между пробуждениями воркера, как задумано.
 */

export interface AlarmLike {
  name: string
  periodInMinutes?: number
}

export interface AlarmInfoLike {
  periodInMinutes?: number
  delayInMinutes?: number
  when?: number
}

export interface AlarmsLike {
  get(name: string, callback: (alarm?: AlarmLike | undefined) => void): void
  create(name: string, alarmInfo: AlarmInfoLike): void
}

export interface RecurringAlarmSpec {
  name: string
  periodInMinutes: number
}

/**
 * Свести периодические alarm'ы к желаемым периодам из `specs`. Идемпотентно на повторных
 * вызовах при неизменных периодах (можно звать на каждом старте воркера и после загрузки
 * рантайм-конфига). Пересоздаёт alarm ТОЛЬКО когда его нет или его период отличается —
 * не сбрасывает таймер существующего alarm'а с тем же периодом.
 */
export function reconcileRecurringAlarms(alarms: AlarmsLike, specs: RecurringAlarmSpec[]): void {
  for (const spec of specs) {
    alarms.get(spec.name, (existing) => {
      if (existing && existing.periodInMinutes === spec.periodInMinutes) return
      alarms.create(spec.name, {
        periodInMinutes: spec.periodInMinutes,
        delayInMinutes: spec.periodInMinutes,
      })
    })
  }
}
