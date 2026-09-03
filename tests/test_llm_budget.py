"""A-08: усечение входа по приоритетам блоков с сохранением обязательных."""

from __future__ import annotations

from core.platform.llm.budget import KIND_PRIORITY, InputBlock, fit_blocks


def test_kind_priority_order_resume_highest_facts_lowest():
    assert KIND_PRIORITY["resume"] > KIND_PRIORITY["vacancy"]
    assert KIND_PRIORITY["vacancy"] > KIND_PRIORITY["history"]
    assert KIND_PRIORITY["history"] > KIND_PRIORITY["facts"]


def test_under_budget_unchanged():
    blocks = [
        InputBlock(kind="resume", text="RESUME", required=True),
        InputBlock(kind="vacancy", text="VACANCY"),
        InputBlock(kind="facts", text="FACTS"),
    ]
    fit = fit_blocks(blocks, max_chars=10_000)
    assert fit.truncated is False
    assert "RESUME" in fit.text
    assert "VACANCY" in fit.text
    assert "FACTS" in fit.text
    assert fit.final_chars == fit.original_chars


def test_long_context_keeps_required_drops_facts_first():
    """Длинный контекст: факты режутся первыми, обязательное резюме остаётся целиком."""
    resume = "RESUME-" + ("R" * 200)
    vacancy = "VACANCY-" + ("V" * 400)
    history = "HISTORY-" + ("H" * 400)
    facts = "FACTS-" + ("F" * 800)

    fit = fit_blocks(
        [
            InputBlock(kind="resume", text=resume, required=True),
            InputBlock(kind="vacancy", text=vacancy, required=True),
            InputBlock(kind="history", text=history),
            InputBlock(kind="facts", text=facts),
        ],
        max_chars=900,
    )

    assert fit.truncated is True
    assert fit.final_chars <= 900
    # Обязательные блоки — целиком (бюджет 900 > resume+vacancy+sep).
    assert resume in fit.text
    assert vacancy in fit.text
    # Факты — первая жертва: либо исчезли, либо заметно ужаты.
    facts_block = next(b for b in fit.blocks if b.kind == "facts")
    assert len(facts_block.text) < len(facts)
    # История не обязана выжить, но если факты ещё не пусты — история не должна
    # быть тронута сильнее фактов (priority).
    history_block = next(b for b in fit.blocks if b.kind == "history")
    if facts_block.text.strip():
        assert history_block.text == history


def test_required_blocks_preserved_when_optional_exhausted():
    """Когда optional уже съедены — обязательные остаются; режется низкий priority среди них."""
    resume = "RESUME_MARK" + ("r" * 100)
    vacancy = "VACANCY_MARK" + ("v" * 500)
    facts = "FACTS_MARK" + ("f" * 500)

    fit = fit_blocks(
        [
            InputBlock(kind="resume", text=resume, required=True),
            InputBlock(kind="vacancy", text=vacancy, required=True),
            InputBlock(kind="facts", text=facts),
        ],
        max_chars=250,
    )

    assert fit.truncated is True
    assert fit.final_chars <= 250
    # Optional facts должны уйти (или почти), resume как высший priority среди required — жив.
    facts_block = next(b for b in fit.blocks if b.kind == "facts")
    assert facts_block.text.strip() == "" or "FACTS_MARK" not in fit.text or len(
        facts_block.text
    ) < 50
    assert "RESUME_MARK" in fit.text
    # Вакансия (ниже resume) может быть ужата, но маркер префикса — если место есть.
    resume_block = next(b for b in fit.blocks if b.kind == "resume")
    assert resume_block.text.startswith("RESUME_MARK") or "RESUME_MARK" in fit.text


def test_label_included_in_join():
    fit = fit_blocks(
        [
            InputBlock(kind="resume", text="body", label="## Резюме", required=True),
            InputBlock(kind="facts", text="x" * 1000),
        ],
        max_chars=80,
    )
    assert fit.text.startswith("## Резюме\nbody")
    assert fit.final_chars <= 80
