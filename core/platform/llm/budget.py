"""Бюджет входа LLM: усечение по приоритетам блоков.

Вместо россыпи `MAX_*_CHARS` на модуль — один fit: режем сначала низкоприоритетные
блоки (факты → история → вакансия → резюме), обязательные (`required=True`) сохраняем
целиком, пока хватает места; при крайней нехватке ужимаем их в последнюю очередь.

`LLM_MAX_INPUT_CHARS` остаётся аварийным потолком в `OpenRouterChatModel._preflight_guards`
(жёсткая ошибка, не silent truncate). Сюда его не подмешиваем как дефолт fit — у фичи
свой осмысленный `max_chars` при сборке контекста.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

# Чем выше число — тем позже блок режется (резюме важнее фактов).
KIND_PRIORITY: dict[str, int] = {
    "resume": 100,
    "vacancy": 80,
    "history": 60,
    "facts": 40,
    "other": 20,
}

_DEFAULT_ELLIPSIS = "\n[…обрезано]"


@dataclass(slots=True)
class InputBlock:
    """Именованный кусок входа LLM.

    `kind` — канон приоритета (`resume` / `vacancy` / `history` / `facts` / `other`)
    или своё имя (тогда priority как у `other`, либо явный `priority=`).
    `required` — обязательный блок: не выкидываем целиком, пока есть необязательные.
    """

    kind: str
    text: str
    required: bool = False
    priority: int | None = None
    label: str = ""

    def effective_priority(self) -> int:
        if self.priority is not None:
            return self.priority
        return KIND_PRIORITY.get(self.kind, KIND_PRIORITY["other"])

    def render(self) -> str:
        body = self.text.strip()
        if not body:
            return ""
        if self.label:
            return f"{self.label}\n{body}"
        return body


@dataclass(slots=True, frozen=True)
class BudgetFit:
    """Результат укладки блоков в бюджет."""

    blocks: tuple[InputBlock, ...]
    text: str
    truncated: bool
    original_chars: int
    final_chars: int


def _join(blocks: Sequence[InputBlock], separator: str) -> str:
    parts = [b.render() for b in blocks]
    return separator.join(p for p in parts if p)


def _total_chars(blocks: Sequence[InputBlock], separator: str) -> int:
    return len(_join(blocks, separator))


def _truncate_body(text: str, keep: int, ellipsis: str) -> str:
    """Префикс тела так, чтобы `strip(body) + marker` укладывался в `keep` символов render."""
    text = text.strip()
    if keep <= 0 or not text:
        return ""
    if len(text) <= keep:
        return text
    marker = ellipsis or ""
    body_budget = keep - len(marker)
    if body_budget <= 0:
        return text[:keep]
    return text[:body_budget].rstrip() + marker


def _shrink_to_render_len(block: InputBlock, target: int, ellipsis: str) -> InputBlock:
    """Ужать блок так, чтобы `len(render()) <= target` (target=0 → пусто)."""
    if target <= 0:
        return replace(block, text="", label="" if not block.required else block.label)

    rendered = block.render()
    if len(rendered) <= target:
        return block

    if block.label:
        prefix = f"{block.label}\n"
        if target <= len(prefix):
            # Места только под label — для optional сносим; для required оставляем крошку тела.
            if not block.required:
                return replace(block, text="", label="")
            return replace(block, text=_truncate_body(block.text, 1, ellipsis))
        body_keep = target - len(prefix)
        return replace(block, text=_truncate_body(block.text, body_keep, ellipsis))

    return replace(block, text=_truncate_body(block.text, target, ellipsis))


def fit_blocks(
    blocks: Sequence[InputBlock],
    *,
    max_chars: int,
    separator: str = "\n\n",
    ellipsis: str = _DEFAULT_ELLIPSIS,
) -> BudgetFit:
    """Уложить блоки в `max_chars`, режа с низкого приоритета.

    Порядок жертв: необязательные по возрастанию priority, затем обязательные
    (тоже с низкого priority). Уменьшение `render()` блока на X уменьшает join на ≥ X.
    """
    if max_chars < 0:
        raise ValueError("max_chars должен быть >= 0")

    working = [
        InputBlock(
            kind=b.kind,
            text=b.text or "",
            required=b.required,
            priority=b.priority,
            label=b.label,
        )
        for b in blocks
    ]
    original = _total_chars(working, separator)
    if original <= max_chars:
        text = _join(working, separator)
        return BudgetFit(
            blocks=tuple(working),
            text=text,
            truncated=False,
            original_chars=original,
            final_chars=len(text),
        )

    # Резать первыми: optional → низкий priority → исходный индекс.
    order = sorted(
        range(len(working)),
        key=lambda i: (working[i].required, working[i].effective_priority(), i),
    )

    truncated = False
    for idx in order:
        current = _total_chars(working, separator)
        if current <= max_chars:
            break
        overflow = current - max_chars
        block = working[idx]
        rendered_len = len(block.render())
        if rendered_len == 0:
            continue

        # Optional можно обнулить; required — минимум 1 символ render, пока блок не пуст.
        raw_target = rendered_len - overflow
        target = max(0, raw_target) if not block.required else max(1, raw_target)

        new_block = _shrink_to_render_len(block, target, ellipsis)
        if new_block.render() != block.render():
            working[idx] = new_block
            truncated = True

    text = _join(working, separator)
    # Страховка: если join всё ещё больше (маркер/label-краевые случаи) — жёсткий кап.
    if len(text) > max_chars:
        text = _truncate_body(text, max_chars, ellipsis)
        truncated = True

    return BudgetFit(
        blocks=tuple(working),
        text=text,
        truncated=truncated,
        original_chars=original,
        final_chars=len(text),
    )


__all__ = [
    "KIND_PRIORITY",
    "InputBlock",
    "BudgetFit",
    "fit_blocks",
]
