"""Демо агента для ДЗ1: обычный сценарий и сценарий со сбоем инструмента.

Живой прогон (нужен ключ провайдера, ключ берётся из окружения):

    AGENT_BASE_URL=... AGENT_MODEL=... AGENT_API_KEY=... python -m agent.demo --yes

Сценарий со сбоем: чтение вакансий падает по таймауту дважды, агент не должен выдумывать
данные — в журнале видно ошибку и честный ответ.

Офлайн-проверка цикла без сети и ключа (записанные ответы):

    python -m agent.demo --scripted --yes
"""

from __future__ import annotations

import argparse
import os
from collections import deque
from collections.abc import Sequence

from agent.config import AgentConfig
from agent.contracts import AgentRun, ConfirmationCard, ToolCall, ToolContext
from agent.loop import run_agent
from agent.providers import OpenAICompatProvider, Provider, ProviderTurn, ScriptedProvider

DEFAULT_GOAL = (
    "Ищу удалённую работу backend-разработчиком в Польше, зарплата от 3500 евро в месяц. "
    "Найди подходящие вакансии, проверь правила страны для гражданина России и отправь "
    "отклик на лучшую."
)


def _parse_faults(values: Sequence[str]) -> dict[str, deque[str]]:
    """`search_vacancies=timeout:2` → очередь двух таймаутов для этого инструмента."""
    faults: dict[str, deque[str]] = {}
    for raw in values:
        target, _, spec = raw.partition("=")
        kind, _, count_text = spec.partition(":")
        count = int(count_text or "1")
        faults.setdefault(target.strip(), deque()).extend([kind.strip()] * count)
    return faults


def _confirmer(auto_yes: bool):
    def confirm(card: ConfirmationCard) -> bool:
        print("\n  Карточка подтверждения (её показывает код, а не модель):")
        print(f"    действие: {card.action}")
        for key, value in card.params.items():
            print(f"    {key}: {value}")
        if auto_yes:
            print("    ответ: да (--yes)\n")
            return True
        try:
            answer = input("    Подтвердить? [y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in {"y", "yes", "д", "да"}

    return confirm


def _print_run(title: str, run: AgentRun, provider: Provider) -> None:
    print(f"\n=== {title} ===")
    print(f"провайдер: {provider.name}")
    print(f"шагов в журнале: {len(run.steps)}, причина остановки: {run.stop_reason}")
    for step in run.steps:
        error = step.error.type if step.error else "—"
        confirmed = step.confirmed_by or "—"
        print(
            f"  шаг {step.index}: {step.tool}  ошибка={error}  "
            f"подтвердил={confirmed}  аргументы={step.args}"
        )
    print(f"токены: вход {run.tokens_in}, выход {run.tokens_out}")
    print(f"ответ: {run.answer}")


def _scripted_provider() -> ScriptedProvider:
    """Записанный нормальный сценарий: поиск → правила → отклик → итог."""
    return ScriptedProvider(
        turns=[
            ProviderTurn(
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="search_vacancies",
                        arguments={
                            "role": "backend",
                            "country": "Польша",
                            "min_salary_eur": 3500,
                            "remote_only": True,
                        },
                    ),
                )
            ),
            ProviderTurn(
                tool_calls=(
                    ToolCall(
                        id="call_2",
                        name="country_rules",
                        arguments={"country": "Польша"},
                    ),
                )
            ),
            ProviderTurn(
                tool_calls=(
                    ToolCall(
                        id="call_3",
                        name="submit_application",
                        arguments={
                            "vacancy_id": "v01",
                            "cover_note": (
                                "Здравствуйте! Меня заинтересовала вакансия Senior Python "
                                "Engineer: 6 лет опыта, Python и Go, готов к B2B-контракту "
                                "и работе из Польши."
                            ),
                        },
                    ),
                )
            ),
            ProviderTurn(
                content=(
                    "Нашёл удалённую вакансию v01 (Senior Python Engineer, Nordwind Labs, "
                    "4500 EUR, B2B). Правила Польши для гражданина России: нужна рабочая виза "
                    "или ВНЖ, для B2B — статус предпринимателя. Отклик поставлен в очередь "
                    "после вашего подтверждения."
                )
            ),
        ]
    )


def _scripted_fault_provider() -> ScriptedProvider:
    """Записанный сценарий сбоя: поиск упал, модель не выдумывает данные и честно говорит."""
    return ScriptedProvider(
        turns=[
            ProviderTurn(
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="search_vacancies",
                        arguments={
                            "role": "backend",
                            "country": "Польша",
                            "min_salary_eur": 3500,
                            "remote_only": True,
                        },
                    ),
                )
            ),
            ProviderTurn(
                content=(
                    "Сервис вакансий не ответил (таймаут), поэтому подобрать варианты я не могу: "
                    "данных нет, и придумывать их я не буду. Предлагаю повторить поиск позже "
                    "или передать задачу оператору."
                )
            ),
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Демо агента курса (ДЗ1)")
    parser.add_argument("--goal", default=DEFAULT_GOAL)
    parser.add_argument(
        "--fault",
        action="append",
        default=[],
        help="запланированный сбой, например search_vacancies=timeout:2",
    )
    parser.add_argument("--yes", action="store_true", help="подтверждать действия автоматически")
    parser.add_argument(
        "--scripted",
        action="store_true",
        help="офлайн-прогон по записанным ответам (без ключа и сети)",
    )
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument(
        "--scenario",
        choices=["normal", "fault", "both"],
        default="both",
    )
    args = parser.parse_args(argv)

    if args.scripted:
        provider: Provider = _scripted_provider()
    else:
        config = AgentConfig.from_env()
        provider = OpenAICompatProvider(
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            timeout_s=config.timeout_s,
            reasoning_effort=config.reasoning_effort,
        )
        print(f"провайдер: {config.provider}, модель: {config.model}")

    max_steps = args.max_steps or int(os.environ.get("AGENT_MAX_STEPS", "6"))

    if args.scenario in {"normal", "both"}:
        run = run_agent(
            args.goal,
            provider,
            context=ToolContext(confirm=_confirmer(args.yes)),
            max_steps=max_steps,
        )
        _print_run("Сценарий 1: обычная задача", run, provider)

    if args.scenario in {"fault", "both"}:
        faults = _parse_faults(args.fault or ["search_vacancies=timeout:2"])
        fault_provider: Provider = _scripted_fault_provider() if args.scripted else provider
        run = run_agent(
            args.goal,
            fault_provider,
            context=ToolContext(faults=faults, confirm=_confirmer(args.yes)),
            max_steps=max_steps,
        )
        _print_run("Сценарий 2: инструмент вернул ошибку", run, fault_provider)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
