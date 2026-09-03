/**
 * Клиент рантайм-конфига расширения (dom/extension-runtime-config.ts) — разбор конверта с
 * сервера поверх зашитого дефолта: булевы флаги, числа тюнинга клампятся, селекторы проходят
 * CSS-валидацию, неизвестное/битое отбрасывается. Никогда не бросает, всегда полный набор.
 * Запуск: cd extension && npx tsx tests/extension-runtime-config.test.ts
 */
import assert from 'node:assert/strict'

import {
  _resetRuntimeConfigForTests,
  matchesTextSignal,
  parseRuntimeConfig,
} from '../src/dom/extension-runtime-config.ts'

function testBuiltinDefaultsWhenNoOverride() {
  const c = parseRuntimeConfig(null, 'builtin')
  assert.equal(c.flags.auto_apply_enabled, true)
  assert.equal(c.flags.auto_apply_hh_enabled, true)
  assert.equal(c.tuning.auto_apply_tick_minutes, 5)
  assert.equal(c.tuning.max_real_applications_per_tick, 1)
  assert.equal(c.tuning.auto_apply_min_real_interval_ms, 120000, 'пол — 2 минуты (owner spec 2026-08-28)')
  assert.deepEqual(c.tuning.auto_apply_delay_ms, [120000, 300000])
  assert.equal(c.tuning.discovery_tick_minutes, 0.5, 'alarm раз в 30с — интервал автопросмотра 30–90с')
  assert.deepEqual(c.tuning.discovery_delay_ms, [30000, 90000])
  assert.equal(
    c.apply_selectors.hh.responseLinkTop,
    '[data-qa="vacancy-response-link-top"]',
    'зашитый селектор hh на месте',
  )
  assert.equal(c.apply_selectors.getmatch.form, '.b-apply-modal__form')
}

function testFlagOverrideAndUnknownFlagDropped() {
  const c = parseRuntimeConfig(
    { version: 3, flags: { auto_apply_hh_enabled: false, bogus_flag: true, discovery_enabled: 0 } },
    'server',
  )
  assert.equal(c.flags.auto_apply_hh_enabled, false, 'флаг применён')
  assert.equal('bogus_flag' in c.flags, false, 'неизвестный флаг отброшен')
  assert.equal(c.flags.discovery_enabled, true, 'не-bool значение флага игнорируется, остаётся дефолт')
  assert.equal(c.version, 3)
}

function testTuningClamped() {
  const c = parseRuntimeConfig(
    {
      version: 2,
      tuning: {
        auto_apply_tick_minutes: 999,
        max_real_applications_per_tick: -5,
        auto_apply_min_real_interval_ms: 1_000,
        tab_load_timeout_ms: 1,
        auto_apply_delay_ms: [90000, 20000],
        apply_reading_delay_ms: [5, 999999],
        bogus_key: 42,
      },
    },
    'server',
  )
  assert.equal(c.tuning.auto_apply_tick_minutes, 60, 'кламп по верхней границе')
  assert.equal(c.tuning.auto_apply_tick_minutes % 1, 0, 'целые минуты округляются до целого')
  assert.equal(c.tuning.max_real_applications_per_tick, 1, 'кламп по нижней границе')
  assert.equal(c.tuning.auto_apply_min_real_interval_ms, 120000, 'мин-интервал не опускается ниже 2 мин')
  assert.equal(c.tuning.tab_load_timeout_ms, 5000, 'кламп по нижней границе')
  assert.deepEqual(c.tuning.auto_apply_delay_ms, [20000, 90000], 'пара нормализуется min≤max')
  assert.deepEqual(c.tuning.apply_reading_delay_ms, [5, 60000], 'верхний конец пары склампан')
}

function testDiscoveryTickMinutesKeepsFraction() {
  // discovery_tick_minutes = период chrome.alarms; 0.5 (= 30с) НЕ должно округляться до 1.
  const c = parseRuntimeConfig(
    { version: 2, tuning: { discovery_tick_minutes: 0.5 } },
    'server',
  )
  assert.equal(c.tuning.discovery_tick_minutes, 0.5, 'дробное значение периода alarm сохранено')
  // ниже пола (0.5) — кламп, не округление
  const low = parseRuntimeConfig({ version: 2, tuning: { discovery_tick_minutes: 0.1 } }, 'server')
  assert.equal(low.tuning.discovery_tick_minutes, 0.5, 'кламп по нижней границе 0.5')
}

function testSelectorValidationRejectsRegexAndUnknownKey() {
  const c = parseRuntimeConfig(
    {
      version: 4,
      apply_selectors: {
        hh: {
          responseLinkTop: 'a.new-response-button',
          letterTextarea: '/injected-regex/',
          bogusKey: '.whatever',
        },
        unknownPlatform: { x: '.y' },
      },
    },
    'server',
  )
  assert.equal(c.apply_selectors.hh.responseLinkTop, 'a.new-response-button', 'валидный селектор применён')
  assert.equal(
    c.apply_selectors.hh.letterTextarea,
    '[data-qa="vacancy-response-popup-form-letter-input"]',
    'регекс отклонён, остаётся зашитый дефолт',
  )
  assert.equal('bogusKey' in c.apply_selectors.hh, false, 'неизвестный ключ отброшен')
  assert.equal('unknownPlatform' in c.apply_selectors, false, 'неизвестная площадка отброшена')
}

function testGarbageEnvelopeFallsBackToDefaults() {
  for (const junk of [undefined, 42, 'nope', [], { version: 'x' }]) {
    const c = parseRuntimeConfig(junk, 'server')
    assert.equal(c.flags.auto_apply_enabled, true)
    assert.equal(c.tuning.auto_apply_tick_minutes, 5)
  }
}

function testParseSelectorsGetmatch() {
  const base = parseRuntimeConfig(null, 'builtin')
  assert.ok(base.parse_selectors.getmatch.title.includes('vacancy__title'), 'зашитый парс-селектор')
  const c = parseRuntimeConfig(
    {
      version: 2,
      parse_selectors: { getmatch: { title: '.new-title', bogus: '.x' }, mystery: { a: '.b' } },
    },
    'server',
  )
  assert.equal(c.parse_selectors.getmatch.title, '.new-title')
  assert.equal('bogus' in c.parse_selectors.getmatch, false)
  assert.equal('mystery' in c.parse_selectors, false)
}

function testTextSignalsUnionAndMatch() {
  _resetRuntimeConfigForTests()
  const base = parseRuntimeConfig(null, 'builtin')
  assert.ok(base.text_signals.getmatch.archived.includes('вакансия снята'))

  const c = parseRuntimeConfig(
    {
      version: 3,
      text_signals: {
        getmatch: { archived: ['Снята с публикации', 123], nope: ['x'] },
        hh: { already_applied: ['теперь вы в откликах'] },
      },
    },
    'server',
  )
  assert.ok(c.text_signals.getmatch.archived.includes('вакансия снята'), 'дефолт сохранён (union)')
  assert.ok(
    c.text_signals.getmatch.archived.includes('снята с публикации'),
    'новая подстрока добавлена, нижний регистр',
  )
  assert.equal('nope' in c.text_signals.getmatch, false)
}

function testMatchesTextSignalHelper() {
  _resetRuntimeConfigForTests() // сбросить память → builtin
  assert.equal(matchesTextSignal('getmatch', 'archived', 'Эта   ВАКАНСИЯ   СНЯТА с сайта'), true)
  assert.equal(matchesTextSignal('getmatch', 'archived', 'вакансия активна'), false)
  assert.equal(matchesTextSignal('hh', 'already_applied', 'Вы  откликнулись на вакансию'), true)
  assert.equal(matchesTextSignal('getmatch', 'unknown_key', 'что угодно'), false)
}

testBuiltinDefaultsWhenNoOverride()
testFlagOverrideAndUnknownFlagDropped()
testTuningClamped()
testDiscoveryTickMinutesKeepsFraction()
testSelectorValidationRejectsRegexAndUnknownKey()
testGarbageEnvelopeFallsBackToDefaults()
testParseSelectorsGetmatch()
testTextSignalsUnionAndMatch()
testMatchesTextSignalHelper()

console.log('extension-runtime-config.test.ts: OK')
