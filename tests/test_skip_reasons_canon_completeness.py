"""Этап 7 §7.1 (D17): каждый ярлык, который UI/бэкенд реально может отправить в
`skipped_vacancies.skip_reason`, обязан сводиться к непустому канону из `SELF_SKIP_REASONS`.

`canonical_skip_reason` формально тотальна (всегда что-то возвращает), поэтому ценность теста —
не в «не падает», а в том, что известные строки летят в ОЖИДАЕМЫЙ канон, а не куда попало
регексом. Разъезд с `frontend/src/features/jobs/reject-reasons.ts` ловит
`test_skip_reasons_canon_snapshot.py`; этот тест — про полноту множества источников строк.
"""

from __future__ import annotations

from core.domains.opportunities.skip_reasons import SELF_SKIP_REASONS, canonical_skip_reason

# Статичные чипы веба/расширения (SELF_REJECT_REASONS в reject-reasons.ts / skip_reasons.py).
_STATIC_CHIPS = set(SELF_SKIP_REASONS)

# Legacy-строки из БД до переименований/слияний (LEGACY_EXACT в skip_reasons.py и
# reject-reasons.ts — держим синхронно вручную, т.к. это разные языки).
_LEGACY_LABELS = {
    "Зарплата ниже целевой",
    "Грейд ниже Senior+",
    "Грейд не совпадает",
    "Не полная удалёнка",
    "Офис / нет удалёнки",
    "Риск выгорания",
    "Сомнительная компания",
    "Другое",
    "Не интересно",
    "без причины",
    "Не тот стек",
    "Не тот домен",
    "Стек/домен далёкий",
    "Не тот стек / домен",
}

# Хардкод-строки бэкенда вне канона/legacy-карты, которые реально пишутся в БД:
# `api/schemas/jobs.py::JobSkipUpdate.reason` (дефолт kanban drag-skip без выбранной причины) и
# `core/app/scenarios/conversations.py::_apply_archive_disposition` (авто-пропуск по архиву чата).
_BACKEND_HARDCODED_LABELS = {
    "Пропущено вручную",
    "Диалог закрыт",
}

# HR-отказы (не self-skip, другая колонка) не проходят через canonical_skip_reason — не входят.


def test_every_reachable_label_maps_to_nonempty_canon():
    for label in _STATIC_CHIPS | _LEGACY_LABELS | _BACKEND_HARDCODED_LABELS:
        canon = canonical_skip_reason(label)
        assert canon in SELF_SKIP_REASONS, f"{label!r} → {canon!r} не входит в SELF_SKIP_REASONS"


def test_static_chips_are_fixed_points():
    for label in _STATIC_CHIPS:
        assert canonical_skip_reason(label) == label


def test_known_legacy_and_hardcoded_labels_map_as_expected():
    expected = {
        "Зарплата ниже целевой": "Низкая зарплата",
        "Грейд ниже Senior+": "Низкий грейд",
        "Грейд не совпадает": "Низкий грейд",
        "Не полная удалёнка": "Не тот формат",
        "Офис / нет удалёнки": "Не тот формат",
        "Риск выгорания": "Не та роль (IC vs рук)",
        "Сомнительная компания": "Избегать компанию",
        "Другое": "Избегать компанию",
        "Не интересно": "Избегать компанию",
        "без причины": "Избегать компанию",
        "Не тот стек": "Не тот стек/домен",
        "Не тот домен": "Не тот стек/домен",
        "Стек/домен далёкий": "Не тот стек/домен",
        "Не тот стек / домен": "Не тот стек/домен",
        "Пропущено вручную": "Избегать компанию",
        "Диалог закрыт": "Избегать компанию",
    }
    for label, canon in expected.items():
        assert canonical_skip_reason(label) == canon, label


def test_empty_and_none_reason_map_to_avoid_company():
    assert canonical_skip_reason(None) == "Избегать компанию"
    assert canonical_skip_reason("") == "Избегать компанию"
    assert canonical_skip_reason("   ") == "Избегать компанию"
