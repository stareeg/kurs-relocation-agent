/**
 * reconcileRecurringAlarms (schedule-alarms.ts) — MV3-планировщик периодических alarm'ов.
 * Ключевое свойство: повторный вызов (эмуляция рестарта service worker'а) НЕ пересоздаёт
 * alarm с тем же периодом, то есть не сбрасывает его period-таймер. Это и был прод-баг —
 * 5-минутный auto_apply_tick сбрасывался каждым стартом воркера и не срабатывал. При смене
 * периода (правка тюнинга с сервера) alarm пересоздаётся один раз.
 * Запуск: cd extension && npx tsx tests/schedule-alarms.test.ts
 */
import assert from 'node:assert/strict'

import {
  reconcileRecurringAlarms,
  type AlarmsLike,
  type RecurringAlarmSpec,
} from '../src/background/schedule-alarms.ts'

function fakeAlarms() {
  const existing = new Map<string, { name: string; periodInMinutes?: number }>()
  const createCalls: { name: string; info: { periodInMinutes?: number; delayInMinutes?: number } }[] =
    []
  const api: AlarmsLike = {
    get(name, cb) {
      cb(existing.get(name))
    },
    create(name, info) {
      createCalls.push({ name, info })
      existing.set(name, { name, periodInMinutes: info.periodInMinutes })
    },
  }
  return { api, existing, createCalls }
}

const SPECS: RecurringAlarmSpec[] = [
  { name: 'auto_apply_tick', periodInMinutes: 5 },
  { name: 'discovery_tick', periodInMinutes: 1 },
  { name: 'hh_selectors_refresh', periodInMinutes: 30 },
]

function testCreatesAllAlarmsOnFirstRun() {
  const { api, createCalls } = fakeAlarms()
  reconcileRecurringAlarms(api, SPECS)
  assert.equal(createCalls.length, 3, 'первый запуск — создаёт все три alarm')
}

function testSecondRunDoesNotRecreateUnchangedAlarms() {
  const { api, createCalls } = fakeAlarms()
  reconcileRecurringAlarms(api, SPECS) // старт воркера №1
  reconcileRecurringAlarms(api, SPECS) // старт воркера №2 (сообщение из content-script)
  reconcileRecurringAlarms(api, SPECS) // старт воркера №3 (тик discovery_tick)
  assert.equal(
    createCalls.length,
    3,
    'повторные запуски воркера с теми же периодами не пересоздают alarm',
  )
}

function testRecreatesOnlyTheMissingAlarm() {
  const { api, existing, createCalls } = fakeAlarms()
  reconcileRecurringAlarms(api, SPECS)
  createCalls.length = 0
  existing.delete('auto_apply_tick')
  reconcileRecurringAlarms(api, SPECS)
  assert.deepEqual(
    createCalls.map((c) => c.name),
    ['auto_apply_tick'],
  )
}

function testRecreatesAlarmWhenPeriodChanges() {
  const { api, createCalls } = fakeAlarms()
  reconcileRecurringAlarms(api, SPECS)
  createCalls.length = 0
  // Сервер замедлил темп автооткликов: 5 → 10 минут.
  reconcileRecurringAlarms(api, [
    { name: 'auto_apply_tick', periodInMinutes: 10 },
    { name: 'discovery_tick', periodInMinutes: 1 },
    { name: 'hh_selectors_refresh', periodInMinutes: 30 },
  ])
  assert.deepEqual(
    createCalls.map((c) => ({ name: c.name, p: c.info.periodInMinutes })),
    [{ name: 'auto_apply_tick', p: 10 }],
    'только alarm со сменившимся периодом пересоздан',
  )
}

function testCreateInfoCarriesPeriod() {
  const { api, createCalls } = fakeAlarms()
  reconcileRecurringAlarms(api, [{ name: 'auto_apply_tick', periodInMinutes: 5 }])
  assert.deepEqual(createCalls[0].info, { periodInMinutes: 5, delayInMinutes: 5 })
}

testCreatesAllAlarmsOnFirstRun()
testSecondRunDoesNotRecreateUnchangedAlarms()
testRecreatesOnlyTheMissingAlarm()
testRecreatesAlarmWhenPeriodChanges()
testCreateInfoCarriesPeriod()

console.log('schedule-alarms.test.ts: OK')
