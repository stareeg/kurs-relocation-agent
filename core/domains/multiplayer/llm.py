"""LLM-фичи домена multiplayer (реестр LlmFeature — A-06/A-09).

**Три роли, три модели (Э19.8).** Раздел ходит не в тир basic/advanced, а в модели из `.env`:

- «режиссёр» (`MODEL_MULTIPLAYER`) — мир вокруг стола: сцена слота, газета. Тут нужна
  подноготная российского IT: что такое ATS, чем пахнет замороженный бюджет, как звучит
  отраслевое издание.
- «актёр» (`MODEL_MULTIPLAYER_ACTOR`) — прямая речь персонажей: реплика кандидата, реакция на
  штамп. Тут нужна пластичность отыгрыша: шесть амплуа за столом обязаны звучать по-разному,
  а не одним голосом на всех, и нужен низкий TTFT — реплики стримятся прямо за стол.
- «арбитр» (`MODEL_MULTIPLAYER_ARBITER`) — суд: единственное место, где от модели нужен не
  живой текст, а **строгий JSON, который сверяется с фактами движка**. Ошибка тут стоит игроку
  выговора, поэтому сюда ставится модель с самым предсказуемым structured-выходом.

Делить по персонажам («одна модель за волков, другая за хрюш») бессмысленно: обе играют и
тех, и других. Делим по типу работы — сценарий, озвучка, протокол. Побочно это ещё и разводит
нагрузку по трём провайдерам: критический путь фазы (реплики, суд) не стоит в очереди за
фоновой газетой, а upstream rate-limit одной модели не гасит стол целиком.

Роль фичи — в `FEATURE_ROLE`; slug в Python не называется нигде, модель меняется одной
строкой `.env` (`wolves_llm._model_for` разрешает роль в slug на вызове).

**Где `schema`, а где голый текст.** Схема ровно у одной фичи — у судьи, и ровно потому, что
там есть что проверять: `cited_marker` обязан быть одной из двух поданных улик, и движок это
сверяет. Остальные четыре отдают одну короткую фразу: `json_schema` за неё берёт лишние
токены, добавляет отдельный класс отказов (пустой content, обрезанный JSON, ```-забор) и
запрещает стрим — а взамен не даёт ничего, строку не с чем сравнивать. Там работает голый
текст + `sanitize_utterance` (обрезка, бан-лист, снятие случайной JSON-обёртки).

**Математики для модели в этой игре нет по построению.** Счёт, штампы, выговоры, победа и
правда о том, кто волк, живут в `rules.py` и в промпт уезжают как факт. Роль «арбитра» —
не «посчитать», а «сослаться на то, что уже посчитано, и не выдумать третьего».

**Чего требует эта роль от модели.** Тексты идут игроку в лицо: реплика бота, вердикт судьи,
газета — короткие, с юмором, в тон кабинету найма. Отсюда `temperature` выше обычного и
`reasoning_effort="none"`: думать тут не над чем, а скрытый reasoning у «мыслящих по
умолчанию» моделей съедает бюджет токенов и время фазы. Выключение единообразно для любой
модели — платформа шлёт `reasoning.enabled = false`
(`core/platform/llm/openrouter_chat.py`), а не флаг конкретного вендора.
"""

from __future__ import annotations

from core.domains.multiplayer.models import WolvesJudgeOut
from core.platform.llm.registry import LlmFeature, register

WOLVES_SYSTEM = "prompts/multiplayer/wolves_system.md"
WOLVES_LINE_PROMPT = "prompts/multiplayer/wolves_line.md"
WOLVES_JUDGE_PROMPT = "prompts/multiplayer/wolves_judge.md"
WOLVES_TICKER_PROMPT = "prompts/multiplayer/wolves_ticker.md"
WOLVES_BARK_PROMPT = "prompts/multiplayer/wolves_bark.md"
WOLVES_BRIEF_PROMPT = "prompts/multiplayer/wolves_brief.md"

#: Роль → чья это работа. `actor` = прямая речь, `director` = мир и хроника,
#: `arbiter` = протокол: строгий JSON, сверяемый с фактами движка.
ROLE_ACTOR = "actor"
ROLE_DIRECTOR = "director"
ROLE_ARBITER = "arbiter"

# Реплика бота за столом — коротко, с температурой (недетерминизм поверх rule engine).
# Единственная фича, которую мы стримим: игрок видит, как фраза печатается, а не ждёт её
# целиком (Э19.8). Бюджет короче фазы `lines` (30 с) — ответ, приехавший после её конца,
# уже никому не нужен.
WOLVES_LINE = register(
    LlmFeature(
        name="wolves_line",
        tier="basic",
        prompt=WOLVES_LINE_PROMPT,
        # Дефолт; на вызове перебивается температурой амплуа (`wolves_llm.persona_for`) —
        # у продажника и у выгоревшего ветерана разный допустимый разброс.
        temperature=0.8,
        max_tokens=1024,
        budget_ms=22_000,
        retries=1,
        cache_prefix=True,
        # Реплика за столом — не задача на рассуждение; см. шапку модуля.
        reasoning_effort="none",
    )
)
# Оглашение вердикта по иску — единственная фича раздела со schema. Сам вердикт считает
# движок (`rules.claim_is_correct`), модель пишет реплику и называет улику, на которую
# ссылается; `cited_marker` сверяется с иском. Температура была 0.2 «чтобы не выдумывал
# вердикт»; выдумывать больше нечего, а 0.2 давала ту самую сухую канцелярию, из-за которой
# суд читался как отписка (Э19).
#
# Два отличия от остальных фич, оба вынужденные:
# - `reasoning_effort=None` (не `"none"`): арбитр — модель с обязательным reasoning, и
#   `reasoning.enabled=false` она отвергает 400-й. Платформа умеет снять флаг и повторить, но
#   это лишний круг на критическом пути; проще не слать его вовсе.
# - `max_tokens` вдвое выше: при включённом thinking скрытые токены съедают потолок, и при
#   json_schema ответ возвращается пустым (ровно так фича молча падала в заглушку до Э18/Д4).
WOLVES_JUDGE = register(
    LlmFeature(
        name="wolves_judge",
        tier="basic",
        prompt=WOLVES_JUDGE_PROMPT,
        schema=WolvesJudgeOut,
        temperature=0.6,
        max_tokens=2048,
        budget_ms=25_000,
        retries=1,
        cache_prefix=True,
        reasoning_effort=None,
    )
)
# Газета конца слота — одна строка вкуса. Заголовок терпит больше разброса, чем вердикт:
# он ни на что не влияет механически, зато его читают каждый слот и он приедается первым.
WOLVES_TICKER = register(
    LlmFeature(
        name="wolves_ticker",
        tier="basic",
        prompt=WOLVES_TICKER_PROMPT,
        temperature=0.9,
        max_tokens=1024,
        budget_ms=25_000,
        retries=1,
        cache_prefix=True,
        reasoning_effort="none",
    )
)
# Реакция кандидата на свой штамп: секунда живой речи там, где раньше молча падала печать.
# Самая короткая фича раздела — потолок слов вдвое ниже реплики, и бюджет соответствующий.
WOLVES_BARK = register(
    LlmFeature(
        name="wolves_bark",
        tier="basic",
        prompt=WOLVES_BARK_PROMPT,
        temperature=1.0,
        max_tokens=1024,
        budget_ms=15_000,
        retries=1,
        cache_prefix=True,
        reasoning_effort="none",
    )
)
# Сцена слота: одна строка про то, что сегодня за день в кабинете. Не влияет на правила —
# бюллетень и событие уже посчитаны движком, модель их только произносит вслух.
#
# Бюджет длиннее остальных намеренно. Эта фраза не держит ни одну фазу: стартует на входе в
# BULLETIN и принимается в любой момент того же слота (bulletin 8 с + play 35 с). А режиссёра
# регулярно придерживает upstream rate-limit, и на 25 с прогон 2026-08-27 не успевал даже
# доехать до запасной модели — игрок вместо сцены получал статическую заглушку.
WOLVES_BRIEF = register(
    LlmFeature(
        name="wolves_brief",
        tier="basic",
        prompt=WOLVES_BRIEF_PROMPT,
        temperature=0.85,
        max_tokens=1024,
        budget_ms=40_000,
        retries=1,
        cache_prefix=True,
        reasoning_effort="none",
    )
)

FEATURES: tuple[LlmFeature, ...] = (
    WOLVES_LINE,
    WOLVES_JUDGE,
    WOLVES_TICKER,
    WOLVES_BARK,
    WOLVES_BRIEF,
)

#: Кто играет фичу. Единственное место, где закреплено разделение труда между моделями.
FEATURE_ROLE: dict[str, str] = {
    "wolves_line": ROLE_ACTOR,
    "wolves_bark": ROLE_ACTOR,
    "wolves_ticker": ROLE_DIRECTOR,
    "wolves_brief": ROLE_DIRECTOR,
    "wolves_judge": ROLE_ARBITER,
}

PROMPT_PATHS: dict[str, str] = {
    "wolves_system": WOLVES_SYSTEM,
    "wolves_line": WOLVES_LINE_PROMPT,
    "wolves_judge": WOLVES_JUDGE_PROMPT,
    "wolves_ticker": WOLVES_TICKER_PROMPT,
    "wolves_bark": WOLVES_BARK_PROMPT,
    "wolves_brief": WOLVES_BRIEF_PROMPT,
}

__all__ = [
    "FEATURES",
    "FEATURE_ROLE",
    "PROMPT_PATHS",
    "ROLE_ACTOR",
    "ROLE_ARBITER",
    "ROLE_DIRECTOR",
    "WOLVES_SYSTEM",
    "WOLVES_LINE_PROMPT",
    "WOLVES_JUDGE_PROMPT",
    "WOLVES_TICKER_PROMPT",
    "WOLVES_BARK_PROMPT",
    "WOLVES_BRIEF_PROMPT",
    "WOLVES_LINE",
    "WOLVES_JUDGE",
    "WOLVES_TICKER",
    "WOLVES_BARK",
    "WOLVES_BRIEF",
]
