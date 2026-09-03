"""Примитив Pipeline — явная последовательность шагов вместо графового оркестратора.

Шаг = имя + async-функция + зависимости + таймаут + обязательность. Независимые готовые
шаги бегут параллельно (`asyncio.wait`); упавший необязательный шаг не рвёт остальных
(частичная деградация — как у скрининг-пакета). События стрима:
`step_start` / `part` / `step_done` / `done` / `error`.

Домены могут импортировать **только** этот модуль из `core.app` (исключение из правила
«домены не импортируют app»): здесь нет доменного знания, только оркестрация. Сценарии
из `core.app.scenarios` доменам по-прежнему закрыты.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

StepFn = Callable[["PipelineContext"], Awaitable[Any]]


@dataclass
class PipelineContext:
    """Входы пайплайна + результаты уже завершённых шагов.

    Шаг читает зависимости через `ctx["brief"]` / `ctx.get("pitch")`; исходные kwargs —
    через те же ключи, пока шаг с таким именем не завершился.
    """

    inputs: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.results:
            return self.results[key]
        return self.inputs.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if key in self.results:
            return self.results[key]
        return self.inputs[key]


@dataclass(frozen=True, slots=True)
class Step:
    """Описание одного шага пайплайна."""

    name: str
    fn: StepFn
    depends_on: tuple[str, ...] = ()
    timeout: float | None = None
    required: bool = True
    #: При падении необязательного шага — подставить это значение и считать шаг «готовым»
    #: для зависимостей (тихий degrade, как brief → пустой JdBrief). Без фабрики упавший
    #: optional шлёт `error` и кладёт `None`.
    default_factory: Callable[[], Any] | None = None


@dataclass(frozen=True, slots=True)
class PipelineEvent:
    """Кадр стрима пайплайна."""

    type: str  # step_start | part | step_done | done | error
    step: str = ""
    data: Any = None
    message: str = ""
    cause: BaseException | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.step:
            out["step"] = self.step
        if self.data is not None:
            out["data"] = self.data
        if self.message:
            out["message"] = self.message
        return out


class PipelineError(Exception):
    """Упал обязательный шаг — пайплайн останавливается."""

    def __init__(self, message: str, *, step: str = "", cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.step = step
        self.cause = cause


class Pipeline:
    """DAG шагов: готовые независимые — параллельно, остальные ждут зависимости."""

    def __init__(self, steps: list[Step], *, name: str = "pipeline") -> None:
        if not steps:
            raise ValueError("Pipeline без шагов")
        names = [s.name for s in steps]
        if len(names) != len(set(names)):
            raise ValueError(f"дубли имён шагов в Pipeline({name!r})")
        self.name = name
        self._steps: dict[str, Step] = {s.name: s for s in steps}
        for step in steps:
            for dep in step.depends_on:
                if dep not in self._steps:
                    raise ValueError(f"шаг {step.name!r} зависит от неизвестного {dep!r}")
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        state: dict[str, int] = {}  # 0=unseen 1=visiting 2=done

        def visit(name: str) -> None:
            mark = state.get(name, 0)
            if mark == 1:
                raise ValueError(f"цикл зависимостей в Pipeline({self.name!r}) у {name!r}")
            if mark == 2:
                return
            state[name] = 1
            for dep in self._steps[name].depends_on:
                visit(dep)
            state[name] = 2

        for step_name in self._steps:
            visit(step_name)

    async def run(self, **inputs: Any) -> dict[str, Any]:
        """Прогнать до конца; вернуть `{имя_шага: результат}`. Обязательный сбой → PipelineError."""
        final: dict[str, Any] | None = None
        async for event in self.stream(**inputs):
            if event.type == "done":
                final = event.data if isinstance(event.data, dict) else {}
            elif event.type == "error" and event.step and self._steps[event.step].required:
                raise PipelineError(
                    event.message or "шаг упал",
                    step=event.step,
                    cause=event.cause,
                ) from event.cause
        return final or {}

    async def stream(self, **inputs: Any) -> AsyncIterator[PipelineEvent]:
        """Стрим событий по мере готовности шагов (для прогрессивного UI)."""
        ctx = PipelineContext(inputs=dict(inputs))
        pending = set(self._steps)
        running: dict[asyncio.Task[Any], str] = {}
        finished: set[str] = set()
        failed_required: str | None = None

        def ready() -> list[str]:
            return [
                name
                for name in pending
                if name not in running.values()
                and all(dep in finished for dep in self._steps[name].depends_on)
            ]

        def launch(name: str) -> None:
            step = self._steps[name]
            task = asyncio.create_task(self._execute(step, ctx), name=f"{self.name}.{name}")
            running[task] = name

        try:
            while pending or running:
                for name in ready():
                    pending.discard(name)
                    yield PipelineEvent(type="step_start", step=name)
                    launch(name)

                if not running:
                    # Цикл/баг: остались pending, но никто не ready и никто не бежит.
                    if pending:
                        raise PipelineError(
                            f"Pipeline({self.name!r}): шаги не запускаются: {sorted(pending)}"
                        )
                    break

                done, _ = await asyncio.wait(running.keys(), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    name = running.pop(task)
                    step = self._steps[name]
                    try:
                        result = task.result()
                    except Exception as exc:  # noqa: BLE001 — классифицируем ниже
                        if step.required:
                            logger.warning(
                                "pipeline %s: обязательный шаг %s упал: %s",
                                self.name,
                                name,
                                exc,
                            )
                            yield PipelineEvent(
                                type="error",
                                step=name,
                                message=str(exc),
                                cause=exc,
                            )
                            failed_required = name
                            break
                        if step.default_factory is not None:
                            result = step.default_factory()
                            logger.warning(
                                "pipeline %s: шаг %s упал, подставляю default: %s",
                                self.name,
                                name,
                                exc,
                            )
                            ctx.results[name] = result
                            finished.add(name)
                            yield PipelineEvent(type="step_done", step=name, data=result)
                            continue
                        logger.warning(
                            "pipeline %s: шаг %s упал (optional): %s",
                            self.name,
                            name,
                            exc,
                        )
                        ctx.results[name] = None
                        finished.add(name)
                        yield PipelineEvent(
                            type="error",
                            step=name,
                            message=str(exc),
                            cause=exc,
                        )
                        continue

                    ctx.results[name] = result
                    finished.add(name)
                    yield PipelineEvent(type="step_done", step=name, data=result)

                if failed_required is not None:
                    await _cancel_tasks(running)
                    return

            yield PipelineEvent(type="done", data=dict(ctx.results))
        finally:
            await _cancel_tasks(running)

    async def _execute(self, step: Step, ctx: PipelineContext) -> Any:
        coro = step.fn(ctx)
        if step.timeout is not None and step.timeout > 0:
            return await asyncio.wait_for(coro, timeout=step.timeout)
        return await coro


async def _cancel_tasks(running: Mapping[asyncio.Task[Any], str]) -> None:
    tasks = list(running)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


__all__ = [
    "Pipeline",
    "PipelineContext",
    "PipelineError",
    "PipelineEvent",
    "Step",
]
