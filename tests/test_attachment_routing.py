"""Э4-3 (chat_image_attachments_2026_08_03.md): ветка вложения в режимах-парсерах.

`resolve_attachment_route` — чистая функция без побочных эффектов: kind классификатора решает
по умолчанию, ярлык-переключатель с чипа (`RouteBadge`, композер) может это переопределить в
любую сторону. `correspondence_dump` форматирует дамп только когда разрешённая ветка —
`correspondence`, независимо от того, откуда она взялась (kind или override).
"""

from __future__ import annotations

from core.domains.assistant.attachments.models import AttachmentAnalysis, AttachmentTurn
from core.domains.assistant.attachments.service import correspondence_dump, resolve_attachment_route


def _analysis(kind: str, **kwargs) -> AttachmentAnalysis:
    defaults = {"title": "t", "summary": "s", "text": "текст со скрина"}
    defaults.update(kwargs)
    return AttachmentAnalysis(kind=kind, **defaults)


def test_route_defaults_to_correspondence_for_correspondence_kind() -> None:
    assert resolve_attachment_route(_analysis("correspondence")) == "correspondence"


def test_route_defaults_to_material_for_other_kinds() -> None:
    assert resolve_attachment_route(_analysis("document")) == "material"
    assert resolve_attachment_route(_analysis("diagram")) == "material"


def test_route_defaults_to_material_when_analysis_missing() -> None:
    assert resolve_attachment_route(None) == "material"


def test_override_wins_over_kind_in_both_directions() -> None:
    # Классификатор угадал «переписка», владелец пометил как материал.
    assert resolve_attachment_route(_analysis("correspondence"), "material") == "material"
    # Классификатор угадал «документ», владелец знает, что это на самом деле переписка.
    assert resolve_attachment_route(_analysis("document"), "correspondence") == "correspondence"


def test_override_wins_even_without_analysis() -> None:
    assert resolve_attachment_route(None, "correspondence") == "correspondence"


def test_dump_uses_turns_when_route_is_correspondence() -> None:
    analysis = _analysis(
        "document",  # kind сам по себе не «переписка» — решает route, не kind
        turns=[AttachmentTurn(speaker="HR", text="Привет"), AttachmentTurn(speaker="Я", text="Хай")],
    )
    route = resolve_attachment_route(analysis, "correspondence")
    assert correspondence_dump(analysis, route) == "HR: Привет\nЯ: Хай"


def test_dump_empty_when_route_is_material_even_for_correspondence_kind() -> None:
    analysis = _analysis("correspondence", turns=[AttachmentTurn(speaker="HR", text="Привет")])
    route = resolve_attachment_route(analysis, "material")
    assert correspondence_dump(analysis, route) == ""


def test_dump_empty_without_analysis_regardless_of_route() -> None:
    assert correspondence_dump(None, "correspondence") == ""
