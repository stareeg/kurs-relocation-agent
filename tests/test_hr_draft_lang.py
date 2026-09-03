"""Э4.5 dual_employment_and_contracting_2026.md: язык HR-черновика (авто, без ручного тумблера)."""

from __future__ import annotations

from core.domains.pipeline.hr_draft import build_hr_draft_system_prompt


async def _build(lang: str = "ru") -> str:
    return await build_hr_draft_system_prompt(
        account_id=1,
        intent="Ответить",
        title="ML Engineer",
        company="Acme",
        vacancy_block="Текст вакансии.",
        hr_feed="HR: когда сможете созвониться?",
        legend="",
        salary_line="от 300 000 ₽",
        lang=lang,  # type: ignore[arg-type]
    )


async def test_ru_default_has_no_english_language_block() -> None:
    prompt = await _build("ru")
    assert "Язык ответа" not in prompt
    assert "Напиши черновик на английском" not in prompt


async def test_en_lang_adds_language_block_after_style_mandate() -> None:
    prompt = await _build("en")
    assert "Напиши черновик на английском" in prompt
    # Мандат стиля (рубленые строки, без канцелярита) остаётся тем же для обоих языков.
    assert "Каждое смысловое предложение - на отдельной строке" in prompt
