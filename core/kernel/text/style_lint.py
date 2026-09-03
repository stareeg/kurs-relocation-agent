"""Детерминированный анти-slop линтер стиля (шаг 30 universal profile).

Чистые функции без LLM и без БД. Два слоя API:

1. Общий (`StyleIssue` / `check_*` / `lint`) - сопроводительные, HR-черновики, легенда,
   усиление резюме и любой прозаический текст. Порог по англицизмам - доля, не факт.
2. Устный скрининг (`StyleViolation` / `lint_pitch` / `lint_spoken_text`) - перенесено из
   `core/screening/style.py`; реэкспорт оставлен там для существующих импортов.

`PitchBlock` живёт здесь, чтобы линтер не зависел от модуля с LLM-вызовом - `pitch.py`
переиспользует этот класс.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Общий API (шаг 30)
# ---------------------------------------------------------------------------

# Канцелярит - ловим словоформы по стему/фразам из плана.
_OFFICIALESE: tuple[str, ...] = (
    "осуществлял",
    "осуществляла",
    "осуществляли",
    "осуществлять",
    "реализовывал",
    "реализовывала",
    "реализовывали",
    "реализовывать",
    "позволяет",
    "позволяют",
    "способствует",
    "способствуют",
    "в рамках",
    "в части",
    "данный",
    "данная",
    "данное",
    "данные",  # осторожно: «данные» как noun тоже матчится - ок для анти-slop
)

# Транслит-англицизмы (кириллица), сверх списка разрешённых технологий.
_TRANSLIT_ANGLICISMS: frozenset[str] = frozenset(
    {
        "инференс",
        "роутинг",
        "пайплайн",
        "продакшен",
        "продакшн",
        "стейкхолдер",
        "стейкхолдеры",
        "скейлить",
        "чекать",
        "драйвить",
        "челлендж",
        "импакт",
        "перформанс",
        "деплой",
        "фидбек",
        "митинг",
        "апдейт",
        "релиз",
        "бэклог",
        "спринт",
        "фасилитация",
    }
)

# Клише ИИ-письма для общего линтера (план шаг 30).
_GENERAL_CLICHES: tuple[str, ...] = (
    "вижу возможность",
    "буду рад обсудить",
    "динамично развивающаяся",
    "динамично развивающейся",
    "командный игрок",
    "синергия",
    "impact",
    "челлендж",
    # Сопроводительные (plans/cover_letter.md, 2026-08-17): пафосные прилагательные и
    # корпоративная вода, по которым HR узнаёт ИИ-письмо с одного взгляда.
    "революционный",
    "инновационный",
    "передовой",
    "уникальный",
    "беспрецедентный",
    "стремлюсь внести вклад",
    "рад возможности стать частью",
    "высокая мотивация",
    "глубокая экспертиза",
    "вы лидеры рынка",
    "меня вдохновляют ваши продукты",
    "важно отметить",
    "в заключение",
)

# Клише ИИ-письма на английском (Э4.3 dual_employment_and_contracting_2026.md) — тот же
# принцип, что _GENERAL_CLICHES, отдельный список: русский словарь на английском тексте
# ловит только латиницу/транслит, не сами фразы.
_EN_CLICHES: tuple[str, ...] = (
    "i am excited to apply",
    "i am writing to express",
    "proven track record",
    "passionate about",
    "fast-paced environment",
    "team player",
    "hit the ground running",
    "wear many hats",
    "results-driven",
    "i believe i would be a great fit",
    "leverage my expertise",
    "value-add",
    "synergy",
    "best-in-class",
)

# Наречия-усилители и вводные слова-заполнители - типичная вода ИИ-письма на английском.
_EN_PADDING_ADVERBS: tuple[str, ...] = (
    "very",
    "highly",
    "extremely",
    "truly",
    "really",
    "significantly",
    "incredibly",
)
_EN_PADDING_PHRASES: tuple[str, ...] = ("i think", "i believe", "i feel that")

_ANGLICISM_RATIO = 25  # флагируем, если > 1 англицизма на 25 слов
_MONOTONY_RUN = 3
_MONOTONY_SHARE = 0.4  # доля предложений с одним и тем же первым словом
_DEFAULT_MAX_LINE_WORDS = 18

_WORD_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9+-]+")
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+./_-]*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…\n])\s+")
_MD_MARKER_RE = re.compile(r"^(\s*[-*#]\s|\s*\d+\.\s)")


class StyleIssue(BaseModel):
    """Одна претензия общего линтера - `code` для логов, `message` для ремонтного промпта."""

    code: str  # anglicism | officialese | punctuation | monotony | cliche | line_length
    message: str
    sample: str = ""


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _normalize_allowed(allowed: set[str] | frozenset[str] | None) -> set[str]:
    if not allowed:
        return set()
    out: set[str] = set()
    for term in allowed:
        t = (term or "").strip()
        if not t:
            continue
        out.add(t.lower())
        # Многословные skills («LLM Ops») - также каждое слово и склеенный вариант.
        parts = _WORD_RE.findall(t)
        for p in parts:
            out.add(p.lower())
        if len(parts) > 1:
            out.add("".join(parts).lower())
            out.add("-".join(parts).lower())
    return out


def _is_allowed_latin(token: str, allowed: set[str]) -> bool:
    low = token.lower().rstrip(".,;:!?")
    if low in allowed:
        return True
    # vLLM / LangGraph - без регистра
    return any(low == a or low.startswith(a) or a.startswith(low) for a in allowed if a.isascii())


def check_anglicisms(text: str, allowed: set[str] | None = None) -> list[StyleIssue]:
    """Латиница и транслит-англицизмы сверх `allowed`; порог - доля (> 1 на 25 слов)."""
    allowed_norm = _normalize_allowed(allowed)
    tokens = _words(text)
    if not tokens:
        return []

    hits: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if _LATIN_WORD_RE.fullmatch(tok):
            if not _is_allowed_latin(tok, allowed_norm):
                hits.append(tok)
            continue
        if low in _TRANSLIT_ANGLICISMS and low not in allowed_norm:
            hits.append(tok)

    # Порог: больше одного на 25 слов (строго > word_count / 25).
    limit = len(tokens) / _ANGLICISM_RATIO
    if len(hits) <= limit:
        return []

    sample = ", ".join(list(dict.fromkeys(hits))[:8])  # уникальные, до 8
    return [
        StyleIssue(
            code="anglicism",
            message=(
                f"слишком много англицизмов ({len(hits)} на {len(tokens)} слов, "
                f"порог 1/{_ANGLICISM_RATIO}) - убрать или заменить русским"
            ),
            sample=sample,
        )
    ]


def check_officialese(text: str) -> list[StyleIssue]:
    """Канцелярит из фиксированного списка."""
    lowered = text.lower()
    issues: list[StyleIssue] = []
    seen: set[str] = set()
    for phrase in _OFFICIALESE:
        if phrase in lowered and phrase not in seen:
            seen.add(phrase)
            issues.append(
                StyleIssue(
                    code="officialese",
                    message=f'канцелярит "{phrase}" - переписать активным глаголом',
                    sample=phrase,
                )
            )
    return issues


def check_punctuation(text: str) -> list[StyleIssue]:
    """Длинные тире, двоеточия перед перечислением, смесь «ёлочек» и прямых кавычек."""
    issues: list[StyleIssue] = []
    lines = [ln for ln in text.splitlines() if ln.strip()] or ([text] if text.strip() else [])

    for line in lines:
        if "—" in line:
            issues.append(
                StyleIssue(
                    code="punctuation",
                    message='длинное тире "—" запрещено - заменить на "-" или перестроить фразу',
                    sample=line.strip()[:120],
                )
            )
        if ":" in line:
            issues.append(
                StyleIssue(
                    code="punctuation",
                    message="двоеточие перед перечислением/пояснением - разбить на строки "
                    "или скобки",
                    sample=line.strip()[:120],
                )
            )
        if ";" in line:
            issues.append(
                StyleIssue(
                    code="punctuation",
                    message='точка с запятой ";" - разбить на отдельные предложения',
                    sample=line.strip()[:120],
                )
            )
        if _MD_MARKER_RE.match(line):
            issues.append(
                StyleIssue(
                    code="punctuation",
                    message="markdown-маркер в начале строки - убрать разметку",
                    sample=line.strip()[:120],
                )
            )

    has_guillemets = ("«" in text) or ("»" in text)
    has_straight = '"' in text
    if has_guillemets and has_straight:
        issues.append(
            StyleIssue(
                code="punctuation",
                message="смешаны «ёлочки» и прямые кавычки - выбрать один стиль",
                sample='«…" и "…"',
            )
        )
    return issues


def _split_sentences(text: str) -> list[str]:
    chunks = [c.strip() for c in _SENTENCE_SPLIT_RE.split(text) if c.strip()]
    if chunks:
        return chunks
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _is_past_tense_start(sentence: str) -> bool:
    words = sentence.strip().split()
    if not words:
        return False
    first = words[0].strip(".,!?«»\"'").lower()
    return len(first) >= 5 and (first.endswith("ла") or first.endswith("ли") or first.endswith("л"))


def check_monotony(text: str) -> list[StyleIssue]:
    """Доля предложений с одинаковым первым словом / подряд глаголы прошедшего времени."""
    sentences = _split_sentences(text)
    if len(sentences) < _MONOTONY_RUN:
        return []

    issues: list[StyleIssue] = []

    run: list[str] = []
    for sent in sentences:
        if _is_past_tense_start(sent):
            run.append(sent)
            if len(run) == _MONOTONY_RUN:
                issues.append(
                    StyleIssue(
                        code="monotony",
                        message=(
                            f"{_MONOTONY_RUN} предложения подряд начинаются с глагола "
                            "прошедшего времени - разбить ритм"
                        ),
                        sample=run[0][:120],
                    )
                )
        else:
            run = []

    first_words: list[str] = []
    for sent in sentences:
        parts = sent.strip().split()
        if parts:
            first_words.append(parts[0].strip(".,!?«»\"'").lower())
    if first_words:
        counts = Counter(first_words)
        n = len(first_words)
        for word, count in counts.items():
            if count >= _MONOTONY_RUN and count / n >= _MONOTONY_SHARE:
                issues.append(
                    StyleIssue(
                        code="monotony",
                        message=(
                            f'слово "{word}" открывает {count} из {n} предложений - '
                            "начать по-другому"
                        ),
                        sample=word,
                    )
                )
    return issues


def check_cliches(text: str) -> list[StyleIssue]:
    """Клише ИИ-письма из фиксированного списка."""
    lowered = text.lower()
    issues: list[StyleIssue] = []
    for cliche in _GENERAL_CLICHES:
        if cliche in lowered:
            issues.append(
                StyleIssue(
                    code="cliche",
                    message=f'клише ИИ-письма "{cliche}" - переписать своими словами',
                    sample=cliche,
                )
            )
    return issues


def check_line_length(text: str, max_words: int = _DEFAULT_MAX_LINE_WORDS) -> list[StyleIssue]:
    """Смысловая строка (по \\n) длиннее `max_words` слов."""
    issues: list[StyleIssue] = []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines and text.strip():
        lines = [text]
    for line in lines:
        word_count = len(line.split())
        if word_count > max_words:
            issues.append(
                StyleIssue(
                    code="line_length",
                    message=f"строка {word_count} слов, больше {max_words} - разбить",
                    sample=line.strip()[:120],
                )
            )
    return issues


def check_en_cliches(text: str) -> list[StyleIssue]:
    """Клише ИИ-письма на английском из фиксированного списка (Э4.3)."""
    lowered = text.lower()
    issues: list[StyleIssue] = []
    for cliche in _EN_CLICHES:
        if cliche in lowered:
            issues.append(
                StyleIssue(
                    code="en_cliche",
                    message=f'AI-письмо cliche "{cliche}" - rewrite in your own words',
                    sample=cliche,
                )
            )
    return issues


def check_en_padding(text: str) -> list[StyleIssue]:
    """Наречия-усилители (very/highly/extremely/…) и «I think/I believe» как заполнители."""
    lowered = text.lower()
    issues: list[StyleIssue] = []
    for adverb in _EN_PADDING_ADVERBS:
        if re.search(rf"\b{re.escape(adverb)}\b", lowered):
            issues.append(
                StyleIssue(
                    code="en_padding",
                    message=f'filler adverb "{adverb}" - cut it or replace with a concrete fact',
                    sample=adverb,
                )
            )
    for phrase in _EN_PADDING_PHRASES:
        if phrase in lowered:
            issues.append(
                StyleIssue(
                    code="en_padding",
                    message=f'hedging filler "{phrase}" - state the fact directly',
                    sample=phrase,
                )
            )
    return issues


def check_en_punctuation(text: str) -> list[StyleIssue]:
    """Длинное тире и двоеточие перед перечислением - та же пунктуация ИИ-письма, на английском."""
    issues: list[StyleIssue] = []
    lines = [ln for ln in text.splitlines() if ln.strip()] or ([text] if text.strip() else [])
    for line in lines:
        if "—" in line or "–" in line:
            issues.append(
                StyleIssue(
                    code="en_punctuation",
                    message="em/en dash forbidden - use a comma or split the sentence",
                    sample=line.strip()[:120],
                )
            )
        if ":" in line:
            issues.append(
                StyleIssue(
                    code="en_punctuation",
                    message="colon before a list/explanation - split into separate lines",
                    sample=line.strip()[:120],
                )
            )
        if _MD_MARKER_RE.match(line):
            issues.append(
                StyleIssue(
                    code="en_punctuation",
                    message="markdown marker at line start - remove formatting",
                    sample=line.strip()[:120],
                )
            )
    return issues


_CHECK_FUNCS: dict[str, Callable[..., list[StyleIssue]]] = {
    "anglicisms": check_anglicisms,
    "officialese": check_officialese,
    "punctuation": check_punctuation,
    "monotony": check_monotony,
    "cliches": check_cliches,
    "line_length": check_line_length,
    "en_cliches": check_en_cliches,
    "en_padding": check_en_padding,
    "en_punctuation": check_en_punctuation,
}

DEFAULT_CHECKS: tuple[str, ...] = (
    "anglicisms",
    "officialese",
    "punctuation",
    "monotony",
    "cliches",
    "line_length",
)

# Анти-slop для английских сопроводительных (cover_letter_intl, Э4.4) - без RU-специфики
# (anglicisms/officialese/punctuation ловят кириллические паттерны). monotony/line_length
# языконезависимы - переиспользуются как есть.
EN_CHECKS: tuple[str, ...] = (
    "en_cliches",
    "en_padding",
    "en_punctuation",
    "monotony",
    "line_length",
)


def _profile_allowed_terms(profile: Any) -> set[str]:
    if profile is None:
        return set()
    skills = getattr(profile, "key_skills", None) or []
    return {str(s).strip() for s in skills if str(s).strip()}


def lint(
    text: str,
    *,
    profile: Any = None,
    allowed_terms: set[str] | frozenset[str] | Sequence[str] | None = None,
    checks: Iterable[str] | None = None,
    max_line_words: int = _DEFAULT_MAX_LINE_WORDS,
) -> list[StyleIssue]:
    """Сборка выбранных проверок. `profile.key_skills` дополняют `allowed_terms`."""
    allowed: set[str] = set(_profile_allowed_terms(profile))
    if allowed_terms:
        allowed |= {str(t).strip() for t in allowed_terms if str(t).strip()}

    selected = tuple(checks) if checks is not None else DEFAULT_CHECKS
    issues: list[StyleIssue] = []
    for name in selected:
        fn = _CHECK_FUNCS.get(name)
        if fn is None:
            continue
        if name == "anglicisms":
            issues.extend(fn(text, allowed))
        elif name == "line_length":
            issues.extend(fn(text, max_line_words))
        else:
            issues.extend(fn(text))
    return issues


# ---------------------------------------------------------------------------
# Устный скрининг (перенесено из core/screening/style.py)
# ---------------------------------------------------------------------------

# Синхронизировано с `prompts/preparation/screening/oral_style.md` п.3 -
# тест `test_screening_style.py` проверяет, что каждый ключ встречается в тексте промпта.
BANNED_TERMS: dict[str, str] = {
    "production": "ПРОМ",
    "продакшен": "ПРОМ",
    "pipeline": "конвейер",
    "пайплайн": "конвейер",
    "guardrails": "ограничители",
    "ai safety": "безопасность модели",
    "llm-as-judge": "модель-проверяющий",
    "eval": "замеры качества",
    "эвалы": "замеры качества",
    "mlops": "эксплуатация моделей",
    "llmops": "эксплуатация моделей",
    "observability": "наблюдаемость",
    "reliability": "надёжность",
    "harness": "обвязка",
    "sota": "современные",
    "enterprise": "корпоративный",
    "инференс": "ответ модели",
    "роутинг": "маршрутизация",
    "impact": "результат",
    "delivery": "сдача",
    "challenge": "сложная задача",
    "ownership": "ответственность",
    "стейкхолдер": "заинтересованная сторона",
    "скейлить": "масштабировать",
    "чекать": "проверять",
    "драйвить": "вести",
}

# п.3 oral_style.md: имена систем/языков разрешены, если не больше шести на весь текст и не
# больше одного в строке.
ALLOWED_NAMES: frozenset[str] = frozenset(
    {"LangGraph", "Langfuse", "MLflow", "vLLM", "RAG", "SQL", "Python", "Postgres", "Neo4j"}
)

# п.7 oral_style.md - запрещённые обороты дословно.
CLICHES: tuple[str, ...] = (
    "хочу рассказать",
    "если интересно - обсудим",
    "вижу возможность",
    "готов масштабировать",
    "мне откликается",
    "закрывал весь цикл",
    "в вашей компании привлекает",
    "с нуля до прода",
    "готов рассматривать",
)

# Реальные примеры с прода (2026-08-13): «готов рассказать подробнее»/«готов обсудить» как
# литеральные фразы в CLICHES обходились простой перестановкой слов - «готов подробнее
# рассказать», «рассказать готов подробнее» и т.п. Модель явно генерализовала запрет по словам,
# а не по фразе целиком. Ловим по совместному присутствию «готов*» + глагола обсуждения/рассказа
# в одной строке, независимо от порядка слов - это и есть смысл запрета п.7 (обезличенная
# готовность обсудить/рассказать в финале вместо конкретного шага или вопроса).
_READY_WORD_RE = re.compile(r"\bготов\w*", re.IGNORECASE)
_DISCUSS_VERB_RE = re.compile(r"\b(рассказ\w*|обсуд\w*|рассмотр\w*)", re.IGNORECASE)


def _check_ready_to_discuss(lines: list[str]) -> list[StyleViolation]:
    violations: list[StyleViolation] = []
    for line in lines:
        if _READY_WORD_RE.search(line) and _DISCUSS_VERB_RE.search(line):
            violations.append(
                StyleViolation(
                    rule="cliche",
                    line=line,
                    detail=f'строка "{line}" - обезличенная готовность обсудить/рассказать '
                    "подробнее (в любом порядке слов) вместо конкретного шага или вопроса - "
                    "переписать",
                )
            )
    return violations


# «Мост к вакансии» отдельно запрещает шаблон «Нужен X - у меня Y», повторённый для каждого
# требования по очереди (см. pitch.md) - живые примеры с прода делали это 3 строки подряд.
# Проверяем по блоку, а не по общему списку строк - только там, где эта конструкция уместна и
# запрещена, чтобы не ловить случайные "Нужен"-начала в других блоках.
_BRIDGE_LABEL = "Мост к вакансии"
_BRIDGE_TEMPLATE_RE = re.compile(r"^(Нужен|Нужна|Нужно|Вам нужен)\b")


def _check_bridge_template(blocks: list[PitchBlock]) -> list[StyleViolation]:
    for block in blocks:
        if block.label != _BRIDGE_LABEL:
            continue
        matches = [line for line in block.lines if _BRIDGE_TEMPLATE_RE.match(line.strip())]
        if len(matches) > 1:
            return [
                StyleViolation(
                    rule="cliche",
                    line=matches[0],
                    detail=f'блок "{_BRIDGE_LABEL}" - {len(matches)} строки подряд начинаются с '
                    '"Нужен/Нужна/Нужно/Вам нужен" (шаблон «требование - у меня факт» по кругу, '
                    "запрещён инструкцией) - оставить максимум один прямой ответ на требование, "
                    "остальные вплести фактом или историей без этой конструкции",
                )
            ]
    return []


_LONG_LINE_WORDS = 18
# 90-120 секунд вслух при ~2.2 слова/сек (`speak_seconds`) - план 2026-07-23 п.3: было
# 60-90 секунд, владелец попросил рассказ подлиннее.
_LENGTH_MIN_WORDS = 195
_LENGTH_MAX_WORDS = 265
_ANCHOR_MIN_LINES = 2

_BANNED_TERMS_RE = re.compile(
    "|".join(rf"\b{re.escape(term)}\b" for term in BANNED_TERMS), re.IGNORECASE
)
_ALLOWED_NAMES_RE = re.compile(
    "|".join(rf"\b{re.escape(name)}\b" for name in ALLOWED_NAMES), re.IGNORECASE
)


class PitchBlock(BaseModel):
    """Один блок рассказа: подпись + произносимые строки (одна строка = одна фраза)."""

    label: str = ""
    lines: list[str] = Field(default_factory=list)


class StyleViolation(BaseModel):
    """Одно нарушение устного стиля - `detail` идёт в ремонтный промпт дословно."""

    rule: str  # banned_term | punctuation | long_line | monotony | cliche | no_anchor | length
    line: str = ""  # строка-нарушитель ("" для правил на весь текст)
    detail: str


def _iter_lines(blocks: list[PitchBlock]) -> list[str]:
    return [line for block in blocks for line in block.lines if line.strip()]


def _check_banned_terms(lines: list[str]) -> list[StyleViolation]:
    violations: list[StyleViolation] = []
    for line in lines:
        match = _BANNED_TERMS_RE.search(line)
        if not match:
            continue
        term = match.group(0).lower()
        replacement = BANNED_TERMS.get(term, "")
        violations.append(
            StyleViolation(
                rule="banned_term",
                line=line,
                detail=f'строка "{line}" - слово "{match.group(0)}" запрещено, '
                f'сказать "{replacement}"',
            )
        )
    return violations


def _check_allowed_names(lines: list[str], full_text: str) -> list[StyleViolation]:
    violations: list[StyleViolation] = []
    for line in lines:
        matches = _ALLOWED_NAMES_RE.findall(line)
        if len(matches) > 1:
            violations.append(
                StyleViolation(
                    rule="banned_term",
                    line=line,
                    detail=f'строка "{line}" - больше одного технического имени в строке, '
                    "оставить одно",
                )
            )
    total = len(_ALLOWED_NAMES_RE.findall(full_text))
    if total > 6:
        violations.append(
            StyleViolation(
                rule="banned_term",
                line="",
                detail=f"технические имена встречаются {total} раз(а) на весь текст - "
                "не больше шести",
            )
        )
    return violations


def _check_pitch_punctuation(lines: list[str]) -> list[StyleViolation]:
    violations: list[StyleViolation] = []
    for line in lines:
        bad_chars = [ch for ch in ("—", ":", ";") if ch in line]
        if bad_chars:
            violations.append(
                StyleViolation(
                    rule="punctuation",
                    line=line,
                    detail=f'строка "{line}" - знак "{bad_chars[0]}" запрещён, '
                    "перестроить фразу или разбить на строки",
                )
            )
        elif _MD_MARKER_RE.match(line):
            violations.append(
                StyleViolation(
                    rule="punctuation",
                    line=line,
                    detail=f'строка "{line}" - markdown-маркер в начале строки, убрать разметку',
                )
            )
    return violations


def _check_long_lines(lines: list[str]) -> list[StyleViolation]:
    violations: list[StyleViolation] = []
    for line in lines:
        word_count = len(line.split())
        if word_count > _LONG_LINE_WORDS:
            violations.append(
                StyleViolation(
                    rule="long_line",
                    line=line,
                    detail=f'строка "{line}" - {word_count} слов, больше {_LONG_LINE_WORDS}, '
                    "разбить на две строки",
                )
            )
    return violations


def _check_pitch_monotony(lines: list[str]) -> list[StyleViolation]:
    violations: list[StyleViolation] = []

    run: list[str] = []
    for line in lines:
        if _is_past_tense_start(line):
            run.append(line)
            if len(run) == _MONOTONY_RUN:
                violations.append(
                    StyleViolation(
                        rule="monotony",
                        line=run[0],
                        detail=f"{_MONOTONY_RUN} строки подряд начинаются с глагола прошедшего "
                        f'времени начиная с "{run[0]}" - разбить ритм',
                    )
                )
        else:
            run = []

    first_words = Counter(line.strip().split()[0].lower() for line in lines if line.strip())
    for word, count in first_words.items():
        if count >= _MONOTONY_RUN:
            violations.append(
                StyleViolation(
                    rule="monotony",
                    line="",
                    detail=f'слово "{word}" открывает {count} строк(и) - начать по-другому',
                )
            )
    return violations


def _check_pitch_cliches(lines: list[str]) -> list[StyleViolation]:
    violations: list[StyleViolation] = []
    for line in lines:
        lowered = line.lower()
        for cliche in CLICHES:
            if cliche in lowered:
                violations.append(
                    StyleViolation(
                        rule="cliche",
                        line=line,
                        detail=f'строка "{line}" - клише ИИ-письма "{cliche}", переписать своими '
                        "словами",
                    )
                )
    return violations


def _normalize_words(text: str) -> set[str]:
    return {w[:5].lower() for w in _WORD_RE.findall(text)}


def _check_anchor(lines: list[str], anchors: list[str]) -> list[StyleViolation]:
    if not anchors:
        return []
    anchor_words: set[str] = set()
    for anchor in anchors:
        anchor_words |= _normalize_words(anchor)
    if not anchor_words:
        return []
    anchor_lines = sum(1 for line in lines if _normalize_words(line) & anchor_words)
    if anchor_lines < _ANCHOR_MIN_LINES:
        return [
            StyleViolation(
                rule="no_anchor",
                line="",
                detail=f"только {anchor_lines} строк(и) опираются на вакансию (нужно минимум "
                f"{_ANCHOR_MIN_LINES}) - привязать формулировки к её требованиям",
            )
        ]
    return []


def _check_length(full_text: str) -> list[StyleViolation]:
    word_count = len(full_text.split())
    if _LENGTH_MIN_WORDS <= word_count <= _LENGTH_MAX_WORDS:
        return []
    return [
        StyleViolation(
            rule="length",
            line="",
            detail=f"весь текст - {word_count} слов, нужно {_LENGTH_MIN_WORDS}-{_LENGTH_MAX_WORDS} "
            "(90-120 секунд вслух)",
        )
    ]


def _lint_lines(
    lines: list[str], *, anchors: list[str], check_length: bool, check_anchor: bool
) -> list[StyleViolation]:
    full_text = " ".join(lines)

    violations: list[StyleViolation] = []
    violations += _check_banned_terms(lines)
    violations += _check_allowed_names(lines, full_text)
    violations += _check_pitch_punctuation(lines)
    violations += _check_long_lines(lines)
    violations += _check_pitch_monotony(lines)
    violations += _check_pitch_cliches(lines)
    violations += _check_ready_to_discuss(lines)
    if check_anchor:
        violations += _check_anchor(lines, anchors)
    if check_length:
        violations += _check_length(full_text)
    return violations


def lint_pitch(blocks: list[PitchBlock], *, anchors: list[str]) -> list[StyleViolation]:
    """Прогнать блоки рассказа через все правила устного стиля, вернуть список нарушений."""
    lines = _iter_lines(blocks)
    violations = _lint_lines(lines, anchors=anchors, check_length=True, check_anchor=True)
    violations += _check_bridge_template(blocks)
    return violations


def lint_spoken_text(text: str) -> list[StyleViolation]:
    """Линт короткого устного текста (например, черновик ответа на HR-вопрос - 2-4 предложения).

    Те же правила словаря/пунктуации/ритма/клише, что у `lint_pitch`, но без правил длины и
    привязки к вакансии - они рассчитаны на 90-120-секундный монолог, а не на пару фраз ответа.
    """
    lines = [line for line in text.split("\n") if line.strip()]
    return _lint_lines(lines, anchors=[], check_length=False, check_anchor=False)


def violations_to_prompt(violations: list[StyleViolation]) -> str:
    """Пронумерованный список претензий по-русски для ремонтного вызова."""
    return "\n".join(f"{i}. {v.detail}" for i, v in enumerate(violations, start=1))


def speak_seconds(text: str) -> int:
    """Слова / 2.2 - грубая оценка длительности устной речи (~130 слов/мин)."""
    words = len(text.split())
    if not words:
        return 0
    return round(words / 2.2)


def issues_to_prompt(issues: list[StyleIssue]) -> str:
    """Пронумерованный список претензий общего линтера для ремонтного вызова (шаг 33)."""
    return "\n".join(
        f"{i}. [{iss.code}] {iss.message}" + (f' (пример: "{iss.sample}")' if iss.sample else "")
        for i, iss in enumerate(issues, start=1)
    )


__all__ = [
    "ALLOWED_NAMES",
    "BANNED_TERMS",
    "CLICHES",
    "DEFAULT_CHECKS",
    "EN_CHECKS",
    "PitchBlock",
    "StyleIssue",
    "StyleViolation",
    "check_anglicisms",
    "check_cliches",
    "check_en_cliches",
    "check_en_padding",
    "check_en_punctuation",
    "check_line_length",
    "check_monotony",
    "check_officialese",
    "check_punctuation",
    "issues_to_prompt",
    "lint",
    "lint_pitch",
    "lint_spoken_text",
    "speak_seconds",
    "violations_to_prompt",
]
