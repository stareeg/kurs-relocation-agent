"""Тесты чеклиста доверия getmatch (gm_trust.GmTrust / trust_to_status)."""

from __future__ import annotations

from core.domains.profile.gm_trust import GmTrust, GmTrustProfileChecks, trust_to_status


def test_empty_trust_zero_filled() -> None:
    """Пустой чеклист — 0/6, все пункты в пропусках, все внешние профили неподключены."""
    status = trust_to_status(GmTrust())
    assert status.available is True
    assert status.trusted is False
    assert status.profile_filled is False
    assert status.filled_count == 0
    assert status.total_checks == 6
    assert len(status.missing_checks) == 6
    assert set(status.missing_connections) == {"LinkedIn", "GitHub", "hh.ru"}


def test_full_trust_no_missing() -> None:
    """Полный чеклист — 6/6, пропусков нет, доверенный."""
    trust = GmTrust(
        trusted=True,
        profile_filled=True,
        profile_checks=GmTrustProfileChecks(
            phone=True,
            email=True,
            photo=True,
            skills=True,
            experience=True,
            education=True,
        ),
        linkedin_connected=True,
        github_connected=True,
        hh_connected=True,
        socials_required=False,
    )
    status = trust_to_status(trust)
    assert status.trusted is True
    assert status.profile_filled is True
    assert status.filled_count == 6
    assert status.missing_checks == []
    assert status.missing_connections == []


def test_partial_trust_reports_specific_missing() -> None:
    """Частичный чеклист — конкретные пропуски (фото и опыт), LinkedIn не подключён."""
    trust = GmTrust(
        trusted=False,
        profile_checks=GmTrustProfileChecks(
            phone=True,
            email=True,
            photo=False,
            skills=True,
            experience=False,
            education=True,
        ),
        linkedin_connected=False,
        github_connected=True,
        hh_connected=True,
    )
    status = trust_to_status(trust)
    assert status.trusted is False
    assert status.filled_count == 4
    assert "Фото" in status.missing_checks
    assert "Опыт" in status.missing_checks
    assert status.missing_connections == ["LinkedIn"]
