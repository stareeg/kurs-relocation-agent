"""LLM-разбор транскрипта собеса.

Транспорт — порт `kernel.ports.llm().complete` (тир из декларации, фича
`debrief`). Парсинг с клампом (сигнал/впечатление/лимиты списков) сохранён без изменений.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from core.config import get_settings
from core.domains.opportunities.prompt import (
    load_candidate_identity,
    load_instructions,
    load_resume,
)
from core.domains.preparation.models import (
    DebriefAnalysis,
    HonestNote,
    MockCompetency,
    QuestionMastery,
    TranscriptSpeaker,
    TranscriptTurn,
    VacancyRecord,
    WeakAnswer,
)
from core.domains.preparation.vacancy_context import truncate_vacancy_text
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200d\ufeff\u2060]+")
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_SOBES_AUDIO_MARKERS = ("🎙️", "Расшифровка аудио", "Расшифровка")
_SOBES_TIMESTAMP_RE = re.compile(r"🔊\s*\d{1,2}:\d{2}")
# Служебные блоки экспорта sobes.tech, которые оказываются между аудио-расшифровками или после
# них: шапка «💬 Вопрос (HH:MM) …», «📷 N скриншот(а/ов)», разделители «---», повторная шапка
# «🎙️ Расшифровка аудио». На расшифровку не влияют, но ломают LLM-сегментацию реплик
# (транскрипт «склеивается» из двух вопросов → вторая шапка + служебка дают мусор, и модель
# возвращает заметно меньше реплик, чем было в разговоре). Вырезаем их целиком.
# Блок «### 💬 Вопрос …» вырезается вместе со всем текстом до следующей «Расшифровки аудио»,
# таймкода-реплики (🔊/🎤), следующего «### 💬 Вопрос» или конца текста — так «вопросы» без
# расшифровки (хвостовая болтовня владельца в экспорте) уходят целиком, а не зависали в хвосте.
_SOBES_QUESTION_HEADER_RE = re.compile(
    r"[ \t]*###\s*💬\s*Вопрос[^\n]*\n(?:[^\n]*\n?)*?(?=🎙️|🔊|🎤|###\s*🎙️|###\s*💬|\Z)",
    flags=re.UNICODE,
)
_SOBES_SCREENSHOT_LINE_RE = re.compile(r"[ \t]*📷\s*[^\n]*скриншот[^\n]*\n?", flags=re.UNICODE)
_SOBES_HR_RULE_RE = re.compile(r"[ \t]*\n---\s*\n", flags=re.UNICODE)
# «Экспортировано: …» в шапке — тоже служебное, до первой «Расшифровки аудио» не доходит
# (там cut по маркеру), но встречается в много-вопросных экспортах между блоками.
_SOBES_EXPORTED_LINE_RE = re.compile(
    r"[ \t]*\*?Экспортировано:[^\n]*\*\?[ \t]*\n", flags=re.UNICODE
)

# DBR-3: поднято с 4096 — ответ теперь дополнительно несёт полный transcript_turns (до 60 реплик),
# одного бюджета на агрегатный разбор уже не хватало бы без обрезки на длинных собесах.
DEBRIEF_MAX_TOKENS = 8192
# DBR-1/DBR-7: потолок на весь LLM-вызов. Без него комбинаторные сетевые ретраи могли тянуться
# 10+ минут без единой ошибки. 75с оказалось мало — легитимная генерация обрывалась по таймауту на
# живом тесте владельца ещё до готового ответа; поднято до 150с (согласовано с HARD_LIMIT_MS на
# фронте, см. use-debrief.ts). Живые прогоны текстового пути укладываются в 15-30с, 150с — запас.
_LLM_TIMEOUT_S = 150.0
_ALLOWED_SIGNALS = {
    "offer_likely",
    "next_stage_likely",
    "ambiguous",
    "rejection_likely",
    "unknown",
}
_ALLOWED_MASTERY = {"confident", "medium", "weak"}
_ALLOWED_FORMATS = {"technical", "system_design", "final", "hr_screening", "other"}
_ALLOWED_SPEAKERS = {"interviewer", "candidate"}
_MAX_TRANSCRIPT_TURNS = 60
_MSK = timezone(timedelta(hours=3))


async def _build_system_prompt(*, account_id: int) -> str:
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    instructions = load_instructions()
    resume = load_resume(data=resume_data)
    identity = load_candidate_identity(data=resume_data)
    today = datetime.now(tz=_MSK).strftime("%Y-%m-%d (%A)")
    return f"""Ты — карьерный коуч и интервью-аналитик. Разбираешь транскрипт прошедшего собеса
с позиции конкретного кандидата ({identity}) и даёшь жёсткий, конкретный feedback.

Сегодня: {today} (Москва, UTC+3) — используй эту дату, если в транскрипте есть время реплики без
даты (только часы:минуты).

## Резюме кандидата

{resume}

## Стратегические приоритеты кандидата

{instructions}

## Что ты делаешь

На входе — фрагменты транскрипта/заметок после собеса. Это может быть:
- расшифровка диктофона / Otter / Read.ai (плохо отформатированная);
- заметки кандидата от первого лица («спросили про X, я ответил Y»);
- скопированный чат из Teams/Zoom;
- любая смесь выше.

Выдели сухой разбор без воды.

## Формат интервью и критерии оценки

Сначала определи формат интервью по транскрипту - от этого зависят критерии оценки:
- "technical" — вопросы про код/архитектуру/технологии вне system design (алгоритмы, стек,
  дебаг). Критерий: техническая корректность, глубина, trade-off'ы.
- "system_design" — проектирование системы/архитектуры под нагрузку. Критерий: полнота
  декомпозиции, узкие места, обоснованность решений, а не синтаксис.
- "final" — финальный созвон (обычно с руководителем/CTO), смесь техники и мотивации/фит.
  Критерий: и техника, и структура истории, коммуникация.
- "hr_screening" — HR/рекрутер, soft skills, мотивация, ожидания, логистика. Критерий:
  структура рассказа (что делал/зачем/результат), коммуникация - НЕ корректность кода.
- "other" — не подходит под предыдущие (или смешанный/непонятный формат).

Прикладывай эти критерии к "weak_answers"/"strong_answers"/"competency_map": для hr_screening
и той части final, что про мотивацию/soft skills, не придирайся к техническим деталям - оценивай
структуру истории и то, насколько понятно и по делу отвечал кандидат.

## "Честный счёт"

Если кандидат САМ в транскрипте явно пометил ответ как нечестный или непроверенный (скинул
код без объяснения, подсказали, не отвечал сам, гуглил при интервьюере) - вынеси такой вопрос
В "honest_notes" И ТОЛЬКО ТУДА: это не провал, а честно раскрытый пробел.

ЖЁСТКОЕ ПРАВИЛО ВЗАИМОИСКЛЮЧЕНИЯ: один вопрос не может одновременно быть и в "weak_answers",
и в "honest_notes". Если вопрос попал в "honest_notes" - удали его из "weak_answers" и не считай
его при выставлении "overall_impression" вообще (ни в плюс, ни в минус, будто вопроса не было).
"overall_impression" ставь только по вопросам вне "honest_notes".

## Правила вывода

1. Верни СТРОГО валидный JSON по схеме:
   {{
     "questions_asked": ["вопрос 1", "вопрос 2", ...],
     "question_mastery": [
       {{"question": "вопрос 1", "level": "confident|medium|weak"}},
       ...
     ],
     "weak_answers": [
       {{"question": "...", "what_went_wrong": "...", "how_to_improve": "...",
         "reference_answer": "эталонный краткий ответ 2-4 предложения"}},
       ...
     ],
     "strong_answers": ["короткое описание сильного ответа", ...],
     "topics_to_study": ["тема 1", "тема 2", ...],
     "competency_map": [
       {{"topic": "...", "level": "confident|medium|weak", "evidence": "1 фраза почему"}},
       ...
     ],
     "honest_notes": [{{"question": "...", "note": "что именно кандидат признал нечестным"}}, ...],
     "interview_format": "technical|system_design|final|hr_screening|other",
     "next_steps_signal": "offer_likely|next_stage_likely|ambiguous|rejection_likely|unknown",
     "overall_impression": 1..10,
     "summary": "2-3 предложения, прямо и по делу",
     "transcript_turns": [
       {{"speaker": "interviewer", "text": "...", "ts": "2026-07-13T13:07:00+03:00"}},
       {{"speaker": "candidate", "text": "...", "ts": null}},
       ...
     ]
   }}
2. Никакого текста до или после JSON. Без markdown-обёртки.
3. "questions_asked": до 12 ключевых вопросов от интервьюера. Если их в транскрипте не видно
   явно — реконструируй по ответам кандидата.
4. "question_mastery": для КАЖДОГО вопроса из "questions_asked" оцени ответ кандидата:
   - "confident" — ответил уверенно, по делу, с конкретикой/примерами из опыта;
   - "medium" — ответил, но поверхностно, без деталей или с оговорками;
   - "weak" — путался, ушёл от ответа, не знал.
   ЖЁСТКОЕ ПРАВИЛО: если в транскрипте НЕТ ответа кандидата на вопрос (задали, а ответ не
   прозвучал/запись обрывается) — НЕ включай этот вопрос в "question_mastery" вообще. Фронт
   честно покажет «Под вопросом». Не выдумывай уровень для вопросов без ответа.
5. "weak_answers": 1-6 пунктов, НИ ОДИН вопрос не повторяется в "honest_notes" (см. правило
   взаимоисключения выше). "what_went_wrong" — конкретно: путаница в терминах, отсутствие
   примера из опыта, неверный trade-off, ушёл от темы. "how_to_improve" — что именно сказать
   в следующий раз, какой кейс из резюме привести. "reference_answer" — короткий эталонный
   ответ (2-4 предложения, не лекция) на именно этот вопрос, с учётом профиля кандидата
   (резюме/приоритеты выше).
6. "strong_answers": 0-5 пунктов, где кандидат ответил уверенно и по делу.
7. "topics_to_study": конкретные темы для подготовки к следующему этапу/похожим собесам.
   Короткие ярлыки, как названия тем подготовки, без воды и без нумерации в самих названиях
   («eval frameworks для RAG», «PostgreSQL row-level security», «K8s probes для LLM-сервисов»),
   НЕ развёрнутые объяснения и НЕ предложения с тире и пояснениями в скобках — просто тема.
8. "competency_map": по каждой затронутой теме/группе смежных тем (не по каждому вопросу
   отдельно, если темы пересекаются) - уровень владения по критериям выбранного формата
   интервью. 2-8 пунктов.
9. "honest_notes": 0-5 пунктов, только явные самопризнания нечестного ответа (см. выше). Пусто,
   если таких маркеров в транскрипте нет - не выдумывай их. Вопрос из "honest_notes" НИКОГДА
   не дублируется в "weak_answers".
10. "interview_format": один из перечисленных выше, определи по факту содержания транскрипта.
11. "next_steps_signal":
    - "offer_likely" — обсуждали ЗП/старт, говорили «вышлем оффер», явный позитив.
    - "next_stage_likely" — назначают следующий этап, явный интерес.
    - "ambiguous" — нейтрально, без явных сигналов.
    - "rejection_likely" — холодные ответы, «мы вернёмся», явный негатив.
    - "unknown" — нет данных.
11. "overall_impression": 1 = провал, 5 = средне, 10 = идеально. Ставь её так, будто вопросов
    из "honest_notes" в транскрипте вообще не было - они не тянут оценку вниз, но и не дают
    очков за пропущенное знание.
12. "summary": сухое резюме — не банальное «было неплохо», а конкретный итог.
13. Никакого нытья про soft skills, если вопросы были технические. Никаких общих советов
    типа «улучшайте коммуникацию». Только адресный feedback.
14. "transcript_turns": дополнительно разбери транскрипт на реплики вопрос/ответ -
    "speaker": "interviewer" (интервьюер) или "candidate" (кандидат). Выдели КАЖДУЮ реплику
    говорящего, какую встретишь в транскрипте - не пропусти ничего содержательного. Длинный
    монолог интервьюера или развёрнутый ответ кандидата оставляй одним turn-ом: убери только
    "воду"/мусор диктофона ("эмм", повторы, неразборчивые обрывки), сохрани хронологию и смысл
    как в исходном транскрипте. Не объединяй подряд идущие реплики одного говорящего в одну
    короткую фразу - это прячет реальный ход разговора. До 60 реплик, каждая до 600 символов.
    Если у реплики есть явное начало от другого говорящего - это новый turn. Если не можешь
    надёжно разделить реплики по говорящим (плохо структурированный текст) - верни пустой список,
    не выдумывай авторство.
15. "ts" у каждой реплики "transcript_turns": если в исходном тексте у реплики есть явная метка
    времени/даты (тайм-код диктофона "🔊 13:07", штамп чата Zoom/Teams, дата в начале строки) -
    переведи её в ISO 8601 с таймзоной +03:00 (недостающую дату бери из "Сегодня" выше). Если
    метки времени нет вообще - оставь "ts": null, НЕ выдумывай его.
"""


def _build_user_prompt(
    record: VacancyRecord, transcript: str, stage_label: str, prior_context: str = ""
) -> str:
    company = record.company or "?"
    position = record.title or "?"
    text = truncate_vacancy_text(record.vacancy_text or "", limit=6000)
    stage_block = f"Этап: {stage_label}\n" if stage_label else ""
    prior_block = (
        f"""## Предыдущие этапы по этой вакансии (для контекста)

{prior_context}

Учитывай, что уже спрашивали и какие были слабые места - на этом этапе логично ждать развития тех же тем.

"""
        if prior_context.strip()
        else ""
    )
    return f"""## Вакансия

Компания: {company}
Позиция: {position}
{stage_block}
### Текст вакансии (выдержка)

{text}

{prior_block}## Транскрипт / заметки после собеса

{transcript.strip()}

Разбери собес и верни JSON по схеме из инструкции. ТОЛЬКО JSON.
"""


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        # Снимаем открывающий fence (``` или ```json). Если закрывающего нет (модель обрезала
        # ответ по max_tokens прямо посередине JSON) — берём всё после открывающего fence.
        lines = raw.split("\n", 1)
        body = lines[1] if len(lines) > 1 else ""
        if body.lower().startswith("json"):
            body = body[4:]
        # Если есть закрывающий fence — обрезаем по нему.
        close_idx = body.find("```")
        if close_idx >= 0:
            body = body[:close_idx]
        return body.strip()
    return raw


def _close_truncated_json(text: str) -> str | None:
    """Восстановить обрезанный по max_tokens JSON: если brace-counting показывает, что объект
    начался, но не закрылся (depth > 0 в конце), дописываем недостающие закрывающие скобки в
    порядке, обратном открытию (стек), и убираем хвост после последней завершённой пары
    ключ-значение (незаконченную строку/число).

    Так debrief на длинных транскриптах (8к токенов, 60 turns) не падает с «no JSON object»,
    когда моделью fence открыт, JSON начат, но генерация оборвалась — частый случай на reasoning-тире.
    """
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None

    in_str = False
    escape = False
    open_stack: list[str] = []  # стек открывающих скобок — закрываем в обратном порядке
    last_valid_end = -1  # позиция после последней `,` или `}`/`]` (точка безопасного обреза)

    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            open_stack.append("}")
        elif ch == "[":
            open_stack.append("]")
        elif ch in ("}", "]"):
            if open_stack and open_stack[-1] == ch:
                open_stack.pop()
                last_valid_end = i + 1
            else:
                # Рассинхрон скобок — дальше чинить небезопасно.
                return None
        elif ch == ",":
            last_valid_end = i
        i += 1

    if not open_stack:
        return None  # объект целостен — нечего чинить

    # Обрезаем хвост после последней безопасной точки (незаконченное значение/строка),
    # затем дописываем закрывающие скобки в порядке, обратном открытию (стек).
    cut = text[start : last_valid_end + 1 if last_valid_end >= 0 else start]
    if cut and cut[-1] == ",":
        cut = cut[:-1]
    repair = cut + "".join(reversed(open_stack))
    return repair


def normalize_transcript(text: str) -> str:
    """Убрать zero-width символы (sobes.tech/OCR) и нормализовать переносы строк."""
    cleaned = _ZERO_WIDTH_RE.sub("", text)
    return cleaned.replace("\r\n", "\n").replace("\r", "\n").strip()


def _strip_sobes_scaffolding(text: str) -> str:
    """Убрать служебные блоки экспорта sobes.tech, оставив только аудио-расшифровку.

    Много-вопросный экспорт («сначала спрашивали про X, потом про Y») состоит из нескольких
    блоков «### 💬 Вопрос … 🎙️ Расшифровка аудио … 📷 скриншот», разделённых «---». Для разбора
    нужна только склейка аудио-реплик: служебные шапки/разделители/скриншот-маркеры ломают
    LLM-сегментацию (модель путается, кто говорит, и возвращает заметно меньше реплик, чем было).
    """
    out = text
    out = _SOBES_EXPORTED_LINE_RE.sub("", out)
    out = _SOBES_QUESTION_HEADER_RE.sub("", out)
    out = _SOBES_SCREENSHOT_LINE_RE.sub("", out)
    out = _SOBES_HR_RULE_RE.sub("\n", out)
    # Повторные шапки «🎙️ Расшифровка аудио» (вторая и далее) — схлопываем в пустую строку,
    # чтобы реплики двух аудио-блоков шли подряд, а не разрывались маркером-дублём.
    out = re.sub(r"(🎙️\s*Расшифровка аудио\s*)", "", out)
    # Три и более подряд пустых строки → две (читаемость, дифф).
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def extract_sobes_transcript(text: str) -> str:
    """sobes.tech export: оставить блок расшифровки, убрать инструкции и дубль вакансии.

    На много-вопросных экспортах (несколько аудио-блоков) — вырезать служебные шапки/разделители
    и схлопнуть повторные маркеры «Расшифровка аудио», чтобы LLM получала чистую ленту реплик.
    """
    normalized = normalize_transcript(text)
    cut = -1
    for marker in _SOBES_AUDIO_MARKERS:
        idx = normalized.find(marker)
        if idx >= 0:
            cut = idx if cut < 0 else min(cut, idx)
    if cut < 0:
        match = _SOBES_TIMESTAMP_RE.search(normalized)
        if match:
            cut = match.start()
    if cut > 0:
        extracted = _strip_sobes_scaffolding(normalized[cut:])
        if len(extracted) >= 20:
            logger.info(
                "debrief: sobes.tech export — взята расшифровка (%d → %d символов)",
                len(normalized),
                len(extracted),
            )
            return extracted
    # Без маркера — служебки нет, просто нормализованный текст.
    return normalized


def _repair_json_text(text: str) -> str:
    """Частые огрехи JSON от LLM: trailing comma."""
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Вытащить JSON-объект из ответа LLM (markdown-обёртка, преамбула, хвост)."""
    raw = (text or "").strip()
    if not raw:
        raise json.JSONDecodeError("empty LLM response", raw, 0)

    candidates = [_strip_code_fences(raw)]
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    if fence:
        candidates.insert(0, fence.group(1).strip())

    for candidate in candidates:
        for attempt in (candidate, _repair_json_text(candidate)):
            try:
                data = json.loads(attempt)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        start = candidate.find("{")
        if start < 0:
            continue
        depth = 0
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    fragment = candidate[start : i + 1]
                    for attempt in (fragment, _repair_json_text(fragment)):
                        try:
                            data = json.loads(attempt)
                            if isinstance(data, dict):
                                return data
                        except json.JSONDecodeError:
                            pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        fragment = match.group()
        for attempt in (fragment, _repair_json_text(fragment)):
            try:
                data = json.loads(attempt)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

    # Последний шанс: модель обрезала ответ по max_tokens посередине JSON (открытый fence,
    # незакрытые объекты/массивы). Пытаемся закрыть скобки и распарсить что есть — partial
    # разбор лучше, чем никакой (фронт покажет то, что удалось вытащить).
    for candidate in candidates:
        repaired = _close_truncated_json(candidate)
        if repaired:
            for attempt in (repaired, _repair_json_text(repaired)):
                try:
                    data = json.loads(attempt)
                    if isinstance(data, dict):
                        logger.warning(
                            "debrief: JSON восстановлен из обрезанного ответа LLM (len=%d)",
                            len(raw),
                        )
                        return data
                except json.JSONDecodeError:
                    pass

    raise json.JSONDecodeError("no JSON object in LLM response", raw, 0)


def _parse_weak_answers(items: Any) -> list[WeakAnswer]:
    out: list[WeakAnswer] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            out.append(WeakAnswer(**item))
        except Exception as exc:  # noqa: BLE001 — пустой/битый weak_answer пропускаем
            logger.warning("debrief: weak_answer пропущен: %s (%s)", item, exc)
    return out


def _parse_str_list(items: Any, limit: int = 30) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            out.append(text[:1000])
        if len(out) >= limit:
            break
    return out


def _parse_competency_map(items: Any) -> list[MockCompetency]:
    out: list[MockCompetency] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level") or "medium").strip()
        if level not in _ALLOWED_MASTERY:
            level = "medium"
        try:
            out.append(
                MockCompetency(
                    topic=str(item.get("topic") or "").strip(),
                    level=level,  # type: ignore[arg-type]
                    evidence=str(item.get("evidence") or "").strip(),
                )
            )
        except Exception as exc:  # noqa: BLE001 — пустой/битый пункт карты пропускаем
            logger.warning("debrief: пункт competency_map пропущен: %s (%s)", item, exc)
    return out[:8]


def _parse_honest_notes(items: Any) -> list[HonestNote]:
    out: list[HonestNote] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            out.append(HonestNote(**item))
        except Exception as exc:  # noqa: BLE001 — пустой/битый honest_note пропускаем
            logger.warning("debrief: honest_note пропущен: %s (%s)", item, exc)
    return out[:5]


def _parse_question_mastery(items: Any) -> list[QuestionMastery]:
    """Оценка ответа по реально заданным вопросам; вопросы без ответа LLM не возвращает."""
    out: list[QuestionMastery] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level") or "medium").strip()
        if level not in _ALLOWED_MASTERY:
            level = "medium"
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        try:
            out.append(
                QuestionMastery(
                    question=question[:1000],
                    level=level,  # type: ignore[arg-type]
                )
            )
        except Exception as exc:  # noqa: BLE001 — битый пункт пропускаем
            logger.warning("debrief: question_mastery пропущен: %s (%s)", item, exc)
    return out[:12]


def _parse_turn_ts(raw: Any) -> str | None:
    """Мягкий парсинг per-turn метки времени от LLM - невалидное/отсутствующее → None (фронт
    сам подставит время начала разбора как фолбэк)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_MSK)
    return dt.isoformat()


def _parse_transcript_turns(items: Any) -> list[TranscriptTurn]:
    out: list[TranscriptTurn] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker") or "").strip()
        if speaker not in _ALLOWED_SPEAKERS:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            out.append(
                TranscriptTurn(
                    speaker=cast(TranscriptSpeaker, speaker),
                    text=text[:600],
                    ts=_parse_turn_ts(item.get("ts")),
                )
            )
        except Exception as exc:  # noqa: BLE001 — битую реплику пропускаем
            logger.warning("debrief: transcript_turn пропущен: %s (%s)", item, exc)
        if len(out) >= _MAX_TRANSCRIPT_TURNS:
            break
    return out


def _normalize_question(text: str) -> str:
    return " ".join(text.strip().casefold().split())


def _dedupe_weak_against_honest(
    weak_answers: list[WeakAnswer], honest_notes: list[HonestNote]
) -> list[WeakAnswer]:
    """Честный счёт: один вопрос не должен одновременно быть провальным ответом и
    честно раскрытым пробелом. Модель (дешёвый тир) не всегда соблюдает это в промпте несмотря на
    явную инструкцию - дожимаем детерминированно, а не полагаемся только на LLM-послушание."""
    honest_questions = {_normalize_question(n.question) for n in honest_notes}
    if not honest_questions:
        return weak_answers
    return [w for w in weak_answers if _normalize_question(w.question) not in honest_questions]


def _parse_from_dict(data: dict[str, Any]) -> DebriefAnalysis:
    """Мягкий парсинг dict → DebriefAnalysis (кламп полей, пропуск битых вложенных)."""
    signal = str(data.get("next_steps_signal") or "unknown").strip()
    if signal not in _ALLOWED_SIGNALS:
        signal = "unknown"

    interview_format = str(data.get("interview_format") or "other").strip()
    if interview_format not in _ALLOWED_FORMATS:
        interview_format = "other"

    impression_raw = data.get("overall_impression")
    if impression_raw is None:
        impression = 5
    else:
        try:
            impression = int(impression_raw)
        except (TypeError, ValueError):
            impression = 5
    impression = max(1, min(10, impression))

    summary = str(data.get("summary") or "").strip()[:2000]
    honest_notes = _parse_honest_notes(data.get("honest_notes"))
    weak_answers = _dedupe_weak_against_honest(
        _parse_weak_answers(data.get("weak_answers"))[:6], honest_notes
    )

    return DebriefAnalysis(
        questions_asked=_parse_str_list(data.get("questions_asked"), limit=12),
        question_mastery=_parse_question_mastery(data.get("question_mastery")),
        weak_answers=weak_answers,
        strong_answers=_parse_str_list(data.get("strong_answers"), limit=5),
        topics_to_study=_parse_str_list(data.get("topics_to_study"), limit=10),
        competency_map=_parse_competency_map(data.get("competency_map")),
        interview_format=interview_format,  # type: ignore[arg-type]
        honest_notes=honest_notes,
        next_steps_signal=signal,  # type: ignore[arg-type]
        overall_impression=impression,
        summary=summary,
        transcript_turns=_parse_transcript_turns(data.get("transcript_turns")),
    )


def _normalize_analysis(data: DebriefAnalysis) -> DebriefAnalysis:
    """Кламп полей после structured output / ручного парсинга."""
    signal = data.next_steps_signal if data.next_steps_signal in _ALLOWED_SIGNALS else "unknown"
    interview_format = (
        data.interview_format if data.interview_format in _ALLOWED_FORMATS else "other"
    )
    impression = max(1, min(10, int(data.overall_impression or 5)))
    summary = (data.summary or "").strip()[:2000]
    honest_notes = list(data.honest_notes[:5])
    weak_answers = _dedupe_weak_against_honest(list(data.weak_answers[:6]), honest_notes)
    competency_map = _parse_competency_map([c.model_dump() for c in data.competency_map])

    return DebriefAnalysis(
        questions_asked=_parse_str_list(data.questions_asked, limit=12),
        question_mastery=_parse_question_mastery([m.model_dump() for m in data.question_mastery]),
        weak_answers=weak_answers,
        strong_answers=_parse_str_list(data.strong_answers, limit=5),
        topics_to_study=_parse_str_list(data.topics_to_study, limit=10),
        competency_map=competency_map,
        interview_format=interview_format,  # type: ignore[arg-type]
        honest_notes=honest_notes,
        next_steps_signal=signal,  # type: ignore[arg-type]
        overall_impression=impression,
        summary=summary,
        transcript_turns=_parse_transcript_turns([t.model_dump() for t in data.transcript_turns]),
    )


def _parse_response(raw: str) -> DebriefAnalysis:
    try:
        data = _extract_json_object(raw)
    except json.JSONDecodeError as exc:
        snippet = (raw[:240] + "…") if len(raw) > 240 else raw
        logger.warning(
            "debrief: невалидный JSON от LLM: %s — len=%d, has_fence=%s, фрагмент: %s",
            exc,
            len(raw),
            raw.strip().startswith("```"),
            snippet,
        )
        raise ValueError(
            "Модель вернула невалидный JSON — попробуй ещё раз или сократи транскрипт"
        ) from exc

    return _normalize_analysis(_parse_from_dict(data))


def _is_degenerate(analysis: DebriefAnalysis) -> bool:
    """Пустой summary — самый дешёвый и надёжный сигнал того, что модель не отработала промпт
    (промпт требует summary всегда), даже если ответ формально распарсился."""
    return not analysis.summary.strip()


async def _run_llm(system: str, user: str) -> DebriefAnalysis:
    """DBR-7: живой тест показал, что `complete_structured` для этой схемы (~10 полей, вложенные
    списки, до 60 transcript_turns) на reasoning-тире ненадёжен сразу в двух направлениях —
    иногда падает 400 "Schema is too complex" у primary-модели, а её внутренний авто-fallback на
    более слабую модель (`openrouter_model_fallback`) тогда возвращает schema-валидный, но
    фактически ПУСТОЙ объект (не исключение — слой structured-output не видит проблемы); иногда
    просто генерирует дольше 150с без ошибки вообще. Обычный текстовый комплишен с тем же
    промптом и тем же (уже проверенным существующими тестами) JSON-парсингом на живых прогонах
    стабильно укладывался в 15-30с и давал полный корректный разбор — используем только его,
    без слоя structured, вместо двух ненадёжных путей одного медленного."""
    raw = await ports.llm().complete(
        "debrief",
        system=system,
        user=user,
        temperature=0.2,
        max_tokens=DEBRIEF_MAX_TOKENS,
    )
    result = _parse_response(raw)
    if _is_degenerate(result):
        raise ValueError("Модель вернула пустой разбор — попробуй ещё раз или сократи транскрипт")
    return result


async def analyze_debrief(
    record: VacancyRecord,
    transcript: str,
    *,
    account_id: int,
    stage_label: str = "",
    prior_context: str = "",
) -> DebriefAnalysis:
    """Разобрать транскрипт собеса. Поднимает LlmError при сбоях LLM.

    `prior_context` — сжатый разбор предыдущих этапов по этой вакансии (вопросы/слабые темы/сигнал),
    чтобы анализ следующего этапа учитывал, что уже было и чего ждать дальше.
    """
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")
    # scenarios.debrief уже вырезал служебку sobes.tech через clean_transcript → extract_sobes_transcript.
    # Повторный вызов здесь давал дубль лога «sobes.tech export» и не находил маркер во второй раз
    # (текст уже чистый) — но на ручных путях (tests, bot_app) transcripts приходят сырыми, поэтому
    # экстракт всё ещё нужен. Идемпотентен: на чистом тексте возвращает его как есть.
    stripped = extract_sobes_transcript(transcript)
    if len(stripped) < 20:
        raise ValueError("Транскрипт слишком короткий для разбора")

    system = await _build_system_prompt(account_id=account_id)
    user = _build_user_prompt(record, stripped, stage_label, prior_context)

    try:
        result = await asyncio.wait_for(_run_llm(system, user), timeout=_LLM_TIMEOUT_S)
    except TimeoutError as exc:
        raise TimeoutError(
            f"Модель долго думает (дольше {_LLM_TIMEOUT_S:.0f}с) — попробуй ещё раз "
            "или сократи транскрипт"
        ) from exc

    event(
        logger,
        "LLM",
        "debrief разобран: %s, слабых=%d, тем=%d, вопросов=%d",
        result.interview_format,
        len(result.weak_answers),
        len(result.topics_to_study),
        len(result.questions_asked),
        vacancy_id=record.vacancy_id,
        interview_format=result.interview_format,
        weak_answers=len(result.weak_answers),
        strong_answers=len(result.strong_answers),
        topics_to_study=len(result.topics_to_study),
        questions_asked=len(result.questions_asked),
        next_steps_signal=result.next_steps_signal,
    )
    return result


__all__ = [
    "analyze_debrief",
    "normalize_transcript",
    "extract_sobes_transcript",
    "_parse_response",
]
