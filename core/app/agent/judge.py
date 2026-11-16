"""Самопроверка шага и судья итога (A-5, уровень 2 по рубрике).

Уровень 1 — проверка шага: модель-судья отвечает «отвечает ли результат шагу плана?»
и дополняет код-эвристику узла `check` (ошибка инструмента по-прежнему проваливает
шаг без вызова модели). Уровень 2 — судья итога: отдельный узел `judge` перед финалом
проверяет, покрыта ли цель и у каждого вывода есть опора-цитата.

Разделение труда (критерий 4.1): цитаты проверяются кодом подстрокой (приём
`core/domains/opportunities/work_terms.py`: нормализация пробелов, casefold, минимум
8 знаков), модель-судья оценивает только смысл. Вывод без опоры-цитаты отправляет
агента на доработку: узел `plan` собирает шаги-доработки, петля ограничена
`RunLimits.max_judge_reworks`, исчерпание — честный финал `judge_failed`.

Сбой судьи — не падение запуска: вердикт `unverified` («не проверяется») идёт как
данные в состояние и события, граф продолжает по прежним правилам (уровень 1 —
прежнее поведение чека, уровень 2 — финал без судебного замечания).

Модель судьи — другой семьи, чем агент (OQ-21): тир `reserve` (DeepSeek V4.1 Flash
через OpenRouter), формат ответа `{reason, verdict}` — причина первой, temperature 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from core.app.agent.budget import budget_from
from core.app.agent.events import AgentEvent, RunObserver
from core.app.agent.prompts import load_prompt
from core.app.agent.state import AgentState, Observation, PlanStep, RunLimits
from core.domains.opportunities.work_terms import quote_in_text
from core.platform.llm.openrouter_chat import _StructuredOutputRunnable

Verdict = Literal["pass", "fail", "unverified"]
"""Вердикт судьи. `unverified` ставит код, когда модель-судья недоступна."""


class JudgeSpec(BaseModel):
    """Structured-выход судьи. Причина первой (формат COWORK), все поля required."""

    reason: str = Field(description="одно предложение: почему такой вердикт")
    verdict: Literal["pass", "fail"] = Field(
        description="pass — проверка пройдена; fail — не пройдена"
    )


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """Вердикт одной проверки: данные для состояния и события `judge_verdict`."""

    level: Literal["step", "final"]
    verdict: Verdict
    reason: str
    quote_failures: tuple[str, ...] = ()
    """Цитаты вывода, которых нет в собранных материалах (проверка кодом)."""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "level": self.level,
            "verdict": self.verdict,
            "reason": self.reason,
        }
        if self.quote_failures:
            payload["quote_failures"] = list(self.quote_failures)
        return payload


# ------------------------------------------------------------------- цитаты кодом

QUOTE_RE = re.compile(r"«([^«»]{8,300})»|\"([^\"\n]{8,300})\"")
"""Цитата вывода: «…» или парные "…" от 8 знаков (короче — совпадёт с любой мелочью)."""


def extract_quotes(text: str) -> list[str]:
    """Цитаты-фрагменты из текста вывода в порядке появления, без дублей."""
    quotes: list[str] = []
    for match in QUOTE_RE.finditer(text or ""):
        quote = (match.group(1) or match.group(2) or "").strip()
        if quote and quote not in quotes:
            quotes.append(quote)
    return quotes


def quote_failures_of(quotes: list[str], evidence: list[str]) -> list[str]:
    """Цитаты, которых нет в собранных материалах (подстрока, приём work_terms)."""
    return [q for q in quotes if not any(quote_in_text(q, e) for e in evidence)]


def final_answer_text(state: AgentState) -> str:
    """Текст итога, который судит судья уровня 2: ответ модели или сводки шагов."""
    observations = state.get("observations") or []
    if observations:
        answer = observations[-1].answer
        if answer:
            return answer
    return "; ".join(s for o in observations for s in o.summaries)


def evidence_texts(state: AgentState) -> list[str]:
    """Материалы, в которых могут жить цитаты: сводки шагов, дословные цитаты
    инструментов (A-5) и карточки вакансий.

    Ответы модели шагов сюда не входят: цитата должна опираться на результаты
    инструментов, а не на слова самого агента (иначе проверка вырождается —
    вывод сходился бы с самим собой).
    """
    texts: list[str] = []
    for obs in state.get("observations") or []:
        texts.extend(obs.summaries)
        texts.extend(obs.evidence_quotes)
    for item in state.get("vacancies") or []:
        if isinstance(item, dict):
            texts.extend(str(v) for v in item.values() if isinstance(v, (str, int, float)))
    return texts


def has_findings(state: AgentState) -> bool:
    """Есть ли собранные данные, на которые вывод обязан опираться цитатой.

    Шаг с ошибкой инструментов данных не даёт; честное «данных нет» после пустого
    поиска цитаты не требует (пустой результат нельзя перекрасить в вывод).
    """
    return any(o.summaries and o.error is None for o in state.get("observations") or [])


def quote_check(state: AgentState) -> tuple[list[str], list[str], bool]:
    """Код-проверка цитат итога: `(проблемные цитаты, все цитаты, вывод без цитат)`.

    Вывод без единой опоры-цитаты при живых данных — провал уровня 2 («вывод без
    цитаты отправляет агента на доработку», критерий 4.1); каждая найденная цитата
    обязана сходиться с материалами подстрокой.
    """
    answer = final_answer_text(state)
    quotes = extract_quotes(answer)
    failures = quote_failures_of(quotes, evidence_texts(state))
    missing = has_findings(state) and not quotes
    return failures, quotes, missing


# ------------------------------------------------------------------- судья шага (уровень 1)


def step_judge_inputs(step: PlanStep, observation: Observation, goal: str) -> str:
    """Вход проверки шага: шаг и его результат, коротко."""
    result = observation.answer or "; ".join(observation.summaries) or "(текста нет)"
    return (
        f"## Цель\n{goal}\n\n"
        f"## Шаг\n{step.id}. {step.title}\nКритерий выполнения: {step.done_criteria}\n\n"
        f"## Результат шага\nинструменты: {', '.join(observation.tools) or '—'}\n"
        f"результат: {result}" + (f"\nошибка: {observation.error}" if observation.error else "")
    )


def judge_step_call(step: PlanStep, observation: Observation, goal: str):
    """Сообщения вызова судьи шага (отдельно — для тестов двойниками)."""
    return [
        SystemMessage(content=load_prompt("judge")),
        HumanMessage(content=step_judge_inputs(step, observation, goal)),
    ]


# ------------------------------------------------------------------- судья итога (уровень 2)

_EVIDENCE_LIMIT = 4000
"""Потолок материалов в промпте судьи итога: вход короткий (замер P0-4)."""


def final_judge_inputs(
    state: AgentState, failures: list[str], quotes: list[str], missing: bool
) -> str:
    """Вход судьи итога: цель, итог, материалы и результат код-проверки цитат."""
    evidence = "\n".join(evidence_texts(state))[:_EVIDENCE_LIMIT]
    code_report = (
        f"цитаты в выводе: {len(quotes)}; вывод без цитат: {'да' if missing else 'нет'}; "
        f"цитаты, которых нет в материалах: {', '.join(failures) if failures else 'нет'}"
    )
    return (
        f"## Цель\n{state['goal']}\n\n"
        f"## Итоговый вывод агента\n{final_answer_text(state) or '(пусто)'}\n\n"
        f"## Собранные материалы (результаты инструментов)\n{evidence or '(пусто)'}\n\n"
        f"## Проверка цитат кодом\n{code_report}"
    )


# ------------------------------------------------------------------- узел судьи итога


def judge_node(
    model: BaseChatModel | None, limits: RunLimits, observer: RunObserver | None = None
) -> Any:
    """Узел `judge` (A-5, уровень 2): цитаты кодом, смысл — моделью, сбой — не падение.

    Проверка кодом детерминирована: найденные в выводе цитаты обязаны сходиться
    с материалами подстрокой — расхождение это провал итога даже при недоступной
    модели-судье. Отсутствие цитат («missing») — не приговор кода: судья видит это
    данными и решает по смыслу, являются ли фразы выводами, требующими опоры
    (отчёт о действии и честное «данных нет» цитаты не требуют). Провал отправляет
    агента на доработку (ребро ведёт в `plan`), пока не исчерпаны `reworks_used`;
    исчерпание — честный финал `judge_failed`. `unverified` — модель недоступна,
    код-проверка чиста: финал без судебного замечания.
    """

    async def _judge(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        failures, quotes, missing = quote_check(state)
        code_reason = ""
        if failures:
            code_reason = f"цитаты не сходятся с материалами: {', '.join(failures)}"

        model_reason: str | None = None
        model_verdict: Verdict | None = None
        budget = budget_from(config)
        if not budget.over_budget():
            if model is not None:
                messages = [
                    SystemMessage(content=load_prompt("judge")),
                    HumanMessage(content=final_judge_inputs(state, failures, quotes, missing)),
                ]
                try:
                    spec = await _StructuredOutputRunnable(model, JudgeSpec, max_retries=1).ainvoke(
                        messages, config=config
                    )
                    model_verdict = spec.verdict
                    model_reason = spec.reason
                except Exception as exc:  # noqa: BLE001 — сбой судьи это unverified, не падение
                    model_reason = f"судья недоступен: {exc}"
            else:
                model_reason = "судья не сконфигурирован"
        else:
            model_reason = "бюджет запуска исчерпан — итог не проверяется"

        if failures:
            verdict: Verdict = "fail"
            reason = code_reason + (f"; судья: {model_reason}" if model_reason else "")
        elif model_verdict == "fail":
            verdict = "fail"
            reason = model_reason or ""
        elif model_verdict is None:
            verdict = "unverified"
            reason = model_reason or "судья не проверил"
        else:
            verdict = "pass"
            reason = model_reason or ""

        reworks = int(state.get("reworks_used", 0))
        out: dict[str, Any] = {
            "judge_verdict": JudgeVerdict(
                level="final", verdict=verdict, reason=reason, quote_failures=tuple(failures)
            ).as_dict(),
            "reworks_used": reworks,
            "model_calls": budget.calls,
            "tokens_in": budget.tokens_in,
            "tokens_out": budget.tokens_out,
        }
        if verdict == "fail":
            if reworks + 1 <= limits.max_judge_reworks:
                out["reworks_used"] = reworks + 1
            else:
                out["stop_reason"] = "judge_failed"
                out["note"] = reason
        if observer is not None:
            observer.emit(
                AgentEvent(
                    type="judge_verdict",
                    payload={
                        "level": "final",
                        "verdict": verdict,
                        "reason": reason,
                        "quote_failures": list(failures),
                        "missing_quotes": missing,
                        "reworks_used": out.get("reworks_used", reworks),
                    },
                    node="judge",
                )
            )
        return out

    return _judge


__all__ = [
    "JudgeSpec",
    "JudgeVerdict",
    "evidence_texts",
    "extract_quotes",
    "final_answer_text",
    "final_judge_inputs",
    "has_findings",
    "judge_node",
    "judge_step_call",
    "quote_check",
    "quote_failures_of",
    "step_judge_inputs",
]
