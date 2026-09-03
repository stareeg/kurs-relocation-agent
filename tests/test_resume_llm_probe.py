"""Живой прогон resume LLM-фич (score_audit, role_fit, strengthen) для анализа качества.

Запуск: `uv run pytest -m llm tests/test_resume_llm_probe.py -s`
"""

from __future__ import annotations

import json
import textwrap
import uuid
from pathlib import Path

import pytest

from core.app.wiring import wire_default_ports
from core.domains.profile.bullet_format import parse_bullets
from core.domains.profile.gap import GapConcept, ResumeGapReport, compute_report
from core.domains.profile.model import ResumeData, to_markdown
from core.domains.profile.score_audit import (
    ResumeScoreAuditLlm,
    _user_payload as audit_user_payload,
    resolve_score_audit_llm,
)
from core.domains.profile.role_fit_llm import _user_payload as role_fit_user_payload
from core.domains.profile.score_criteria import criteria_alignment_checks, format_search_axes_block
from core.domains.profile.strengthen import strengthen_section
from core.domains.profile.context import StrengthenContext, gather_bio_material
from core.domains.profile.strengthen_quality import format_enhancement_directive
from core.kernel import ports

pytestmark = pytest.mark.llm

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "resume_smoke_frontend.json"

_TOP_JOBS: list[tuple[str, str]] = [
    (
        "Senior Frontend Developer (React/TS)",
        "Авито",
    ),
    (
        "Frontend Lead · Design System",
        "Ozon",
    ),
    (
        "Senior React Developer",
        "Продуктовая fintech",
    ),
]


def _load_probe_resume() -> ResumeData:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    data = ResumeData.model_validate(raw)
    sc = data.search_criteria.model_copy(
        update={
            "role_kind": "Делаю руками",
            "market_segment": "E-commerce",
        }
    )
    return data.model_copy(update={"search_criteria": sc})


def _synthetic_report(resume_text: str) -> ResumeGapReport:
    report = compute_report([], resume_text, patterns={})
    report.missing = [
        GapConcept(name="Vue 3", demand_count=40, demand_pct=35.0, present=False),
        GapConcept(name="Module Federation", demand_count=28, demand_pct=24.0, present=False),
        GapConcept(name="GraphQL", demand_count=22, demand_pct=18.0, present=False),
    ]
    return report


def _print_section(title: str, body: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    print(body)


def _audit_quality_notes(raw: ResumeScoreAuditLlm, data: ResumeData) -> list[str]:
    notes: list[str] = []
    abstract_markers = (
        "добавьте",
        "рекоменду",
        "усильте",
        "улучшите",
        "следует",
        "нужно добавить",
    )
    for fix in raw.writing_fixes + raw.role_fit_fixes:
        sug = fix.suggested.strip()
        if len(sug) < 20:
            notes.append(f"⚠ короткий suggested ({fix.label}): {sug!r}")
        if any(m in sug.casefold() for m in abstract_markers):
            notes.append(f"⚠ абстрактный suggested ({fix.label}): {sug[:80]}")
        if " — " in fix.label and fix.section == "experience":
            notes.append(f"⚠ label дублирует должность: {fix.label}")
        if fix.section == "experience" and fix.experience_index is None:
            notes.append(f"⚠ нет experience_index для опыта: {fix.label}")
    exp0 = (data.experience[0].description if data.experience else "") or ""
    parsed = parse_bullets(exp0)
    if not parsed and exp0.strip():
        notes.append(
            f"⚠ описание опыта без маркеров буллетов — parse_bullets=0 строк "
            f"(LLM видит только exp_lines + bullet_catalog)"
        )
    writing_lost = sum(f.points_lost for f in raw.writing_fixes)
    role_lost = sum(f.points_lost for f in raw.role_fit_fixes)
    if raw.writing_score < 90 and not raw.writing_fixes:
        notes.append("⚠ writing_score низкий, но writing_fixes пуст")
    if abs(writing_lost - (100 - raw.writing_score)) > 8 and raw.writing_fixes:
        notes.append(
            f"⚠ сумма writing points_lost ({writing_lost}) "
            f"не бьётся с score {raw.writing_score}"
        )
    if abs(role_lost - (100 - raw.role_fit_score)) > 8 and raw.role_fit_fixes:
        notes.append(
            f"⚠ сумма role_fit points_lost ({role_lost}) "
            f"не бьётся с score {raw.role_fit_score}"
        )
    return notes


@pytest.fixture(scope="module", autouse=True)
def _wire_ports():
    wire_default_ports(force=True)


async def test_resume_llm_probe_score_audit_role_fit_strengthen(capsys):
    from core.config import get_settings

    if not get_settings().openrouter_api_key.strip():
        pytest.skip("нет OPENROUTER_API_KEY")

    data = _load_probe_resume()
    resume_text = to_markdown(data)
    report = _synthetic_report(resume_text)

    _print_section("INPUT: критерии поиска", format_search_axes_block(data))
    checks = criteria_alignment_checks(data, resume_text)
    _print_section(
        "INPUT: criteria_alignment (детерминизм)",
        "\n".join(f"{'✓' if ok else '✗'} {key}" for key, ok in checks),
    )
    exp_desc = data.experience[0].description if data.experience else ""
    _print_section(
        "INPUT: опыт[0] — parse_bullets vs prose",
        f"parse_bullets: {len(parse_bullets(exp_desc))} строк\n"
        f"текст ({len(exp_desc)} симв.):\n{exp_desc[:500]}",
    )
    _print_section("INPUT: user payload score_audit", audit_user_payload(data, report, _TOP_JOBS))

    audit = await resolve_score_audit_llm(data, report, account_id=1, db=None)
    assert audit is not None, "score_audit вернул None — проверь OPENROUTER и фичу resume_score_audit"
    writing_score, role_score, fixes = audit

    from core.domains.profile.llm import SCORE_AUDIT, ROLE_FIT
    from core.domains.profile.score_audit import _load_prompt as load_audit_prompt
    from core.domains.profile.role_fit_llm import _load_prompt as load_role_prompt

    audit_prompt_head = load_audit_prompt(SCORE_AUDIT)[:400]
    _print_section(
        "PROMPT score_audit (head)",
        audit_prompt_head + ("\n…" if len(load_audit_prompt(SCORE_AUDIT)) > 400 else ""),
    )
    if "{{CANDIDATE_IDENTITY}}" in load_audit_prompt(SCORE_AUDIT):
        _print_section("BUG", "score_audit промпт содержит незаменённый {{CANDIDATE_IDENTITY}}")

    raw_audit = await ports.llm().structured(
        "resume_score_audit",
        system=load_audit_prompt(SCORE_AUDIT),
        user=audit_user_payload(data, report, _TOP_JOBS),
        schema=ResumeScoreAuditLlm,
        temperature=0.25,
        cache_key=str(uuid.uuid4()),
    )
    assert isinstance(raw_audit, ResumeScoreAuditLlm)

    audit_report = textwrap.dedent(
        f"""
        writing_score={raw_audit.writing_score} role_fit_score={raw_audit.role_fit_score}
        writing_fixes={len(raw_audit.writing_fixes)} role_fit_fixes={len(raw_audit.role_fit_fixes)}

        WRITING:
        """
    ).strip()
    for i, f in enumerate(raw_audit.writing_fixes, 1):
        audit_report += (
            f"\n  {i}. [{f.label}] −{f.points_lost} | {f.apply_action}\n"
            f"     cur: {f.current[:100]}\n"
            f"     sug: {f.suggested[:160]}\n"
            f"     why: {f.why}"
        )
    audit_report += "\n\nROLE_FIT:"
    for i, f in enumerate(raw_audit.role_fit_fixes, 1):
        audit_report += (
            f"\n  {i}. [{f.label}] −{f.points_lost} | {f.apply_action}\n"
            f"     sug: {f.suggested[:160]}\n"
            f"     why: {f.why}"
        )
    quality = _audit_quality_notes(raw_audit, data)
    if quality:
        audit_report += "\n\nQUALITY FLAGS:\n" + "\n".join(quality)
    _print_section("RESULT score_audit", audit_report)

    _print_section("INPUT: user payload role_fit", role_fit_user_payload(data, report, _TOP_JOBS))
    if "{{CANDIDATE_IDENTITY}}" in load_role_prompt(ROLE_FIT):
        _print_section("BUG", "role_fit промпт — статичный, без identity (ожидаемо для extract)")

    # Strengthen: контекст как у ATS (без PG) vs полный strengthen context
    ats_ctx_text = "\n".join(
        p
        for p in [
            "Топ вакансий (синтетика):\n"
            + "\n".join(f"- {t} · {c}" for t, c in _TOP_JOBS),
            "Разрывы навыков: Vue 3, GraphQL",
        ]
        if p
    )
    ats_ctx = StrengthenContext(
        text=ats_ctx_text,
        has_gap=True,
        has_funnel=False,
        has_top_vacancies=True,
        bio_material=gather_bio_material(data),
    )
    full_ctx = StrengthenContext(
        text=format_enhancement_directive(data) + "\n\n" + ats_ctx_text,
        has_gap=True,
        has_funnel=False,
        has_top_vacancies=True,
        bio_material=gather_bio_material(data),
    )

    original = data.experience[0].description or ""
    weak_result = await strengthen_section(
        "experience",
        original,
        account_id=1,
        role_title=data.position.title or "",
        keep_terms=data.key_skills[:15],
        mode="refine",
        ctx=ats_ctx,
    )
    strong_result = await strengthen_section(
        "experience",
        original,
        account_id=1,
        role_title=data.position.title or "",
        keep_terms=data.key_skills[:15],
        mode="refine",
        ctx=full_ctx,
    )

    from core.domains.profile.strengthen_quality import (
        is_substantive_enhancement,
        token_jaccard_similarity,
    )

    strengthen_report = textwrap.dedent(
        f"""
        ORIGINAL ({len(original)} chars):
        {original[:400]}

        ATS-CTX ONLY (без directive):
        substantive={is_substantive_enhancement(original, weak_result.text)}
        jaccard={token_jaccard_similarity(original, weak_result.text):.2f}
        proposed:
        {weak_result.text[:800]}

        FULL CTX (+ format_enhancement_directive):
        substantive={is_substantive_enhancement(original, strong_result.text)}
        jaccard={token_jaccard_similarity(original, strong_result.text):.2f}
        proposed:
        {strong_result.text[:800]}
        """
    ).strip()
    _print_section("RESULT strengthen exp[0]", strengthen_report)

    # Sanity — хотя бы один вызов дал содержательный результат
    assert raw_audit.writing_score >= 0
    assert writing_score == raw_audit.writing_score
    assert role_score == role_score  # noqa: PLR0124 — smoke bind
    assert weak_result.text.strip()
