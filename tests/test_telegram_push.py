"""TB-6: пуш из веба в Telegram — контракт фазы.

Покрытие:
- enqueue + идемпотентный ключ на минуту (даблклик);
- 409 без линковки / 404 без вакансии;
- рендер текстов по фикстурам (screening / prep / offer);
- handler доставки с моком отправки (без TG/PG).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.security import AccountContext
from core.domains.profile import telegram_link as tl
from core.domains.profile import telegram_push as tp
from core.platform.tasks import MemoryTaskStore, reset_runtime_for_tests
from tests.fake_accounts import FakeAccountsStore

# M7: /api/telegram/push резолвит СВОЙ аккаунт вызывающего (require_account_context), не
# глобального владельца — тесты роутера собирают AccountContext вручную (без FastAPI DI).
_OWNER_CTX = AccountContext(account_id=1, telegram_user_id=42, telegram_username="Owner", role="owner")


@pytest.fixture
def settings_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    store: dict[str, Any] = {}

    async def fake_get(key: str, default: Any = None, *, account_id: Any = None, db: Any = None) -> Any:
        _ = account_id, db
        return store.get(key, default)

    async def fake_set(key: str, value: Any, *, account_id: Any = None, db: Any = None) -> None:
        _ = account_id, db
        store[key] = value

    monkeypatch.setattr(tl, "get_setting", fake_get)
    monkeypatch.setattr(tl, "set_setting", fake_set)
    return store


@pytest.fixture
def accounts(monkeypatch: pytest.MonkeyPatch) -> FakeAccountsStore:
    """In-memory `accounts` — владелец (Этап 2, не через app_settings)."""
    from api.routers.meta import telegram as api_tg

    fake = FakeAccountsStore()
    fake.patch_telegram_link_module(monkeypatch, tl)
    # M7: роутер резолвит СВОЙ аккаунт через get_account_by_telegram_user_id — тот же фейк.
    fake.patch_accounts_module(monkeypatch, api_tg)
    return fake


@pytest.fixture
def runtime():
    return reset_runtime_for_tests(MemoryTaskStore())


def _job(**kwargs: Any) -> Any:
    from core.domains.opportunities.jobs import Job

    base: dict[str, Any] = {
        "vacancy_text": "текст",
        "company": "Acme",
        "title": "PM",
        "vacancy_id": "hh:1",
    }
    base.update(kwargs)
    return Job(**base)


def _link_owner(user_id: int = 42, chat_id: int = 42) -> Any:
    return tl.set_owner(user_id=user_id, chat_id=chat_id, username="Owner")


# --- enqueue / API -----------------------------------------------------------------------------


def test_push_idempotency_key_format() -> None:
    at = datetime(2026, 7, 31, 9, 51, 42, tzinfo=UTC)
    key = tp.push_idempotency_key("vacancy_card", "hh:123", at=at)
    assert key == "tg_push:vacancy_card:hh:123:202607310951"


def test_push_idempotency_key_naive_utc() -> None:
    at = datetime(2026, 7, 31, 9, 51, 0)
    key = tp.push_idempotency_key("offer_summary", "gm:9", at=at)
    assert key == "tg_push:offer_summary:gm:9:202607310951"


@pytest.mark.asyncio
async def test_enqueue_tg_push_idempotent_within_minute(runtime) -> None:
    at = datetime(2026, 7, 31, 9, 51, 10, tzinfo=UTC)
    a = await tp.enqueue_tg_push("vacancy_card", "hh:1", account_id=1, at=at)
    b = await tp.enqueue_tg_push("vacancy_card", "hh:1", account_id=1, at=at.replace(second=50))
    assert a.id == b.id
    assert a.payload == {"kind": "vacancy_card", "vacancy_id": "hh:1", "account_id": 1}
    assert a.idempotency_key == "tg_push:vacancy_card:hh:1:202607310951"
    assert a.account_id == 1

    c = await tp.enqueue_tg_push(
        "vacancy_card", "hh:1", account_id=1, at=datetime(2026, 7, 31, 9, 52, tzinfo=UTC)
    )
    d = await tp.enqueue_tg_push("screening_pack", "hh:1", account_id=1, at=at)
    assert c.id != a.id
    assert d.id != a.id


@pytest.mark.asyncio
async def test_push_409_when_not_linked(
    settings_store: dict[str, Any],
    accounts: FakeAccountsStore,
    monkeypatch: pytest.MonkeyPatch,
    runtime,
) -> None:
    from api.routers.meta import telegram as api_tg
    from api.schemas.telegram import TelegramPushRequest

    monkeypatch.setattr(
        api_tg,
        "get_job_by_vacancy_id",
        AsyncMock(side_effect=AssertionError("vacancy check after owner")),
    )
    with pytest.raises(HTTPException) as exc:
        await api_tg.enqueue_push_response(
            TelegramPushRequest(kind="vacancy_card", vacancy_id="hh:1"), account=_OWNER_CTX
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "Привяжи Telegram в Параметрах"


@pytest.mark.asyncio
async def test_push_404_when_vacancy_missing(
    settings_store: dict[str, Any],
    accounts: FakeAccountsStore,
    monkeypatch: pytest.MonkeyPatch,
    runtime,
) -> None:
    from api.routers.meta import telegram as api_tg
    from api.schemas.telegram import TelegramPushRequest

    await _link_owner(user_id=1, chat_id=1)
    monkeypatch.setattr(api_tg, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    caller = AccountContext(account_id=1, telegram_user_id=1, telegram_username="Owner", role="owner")

    with pytest.raises(HTTPException) as exc:
        await api_tg.enqueue_push_response(
            TelegramPushRequest(kind="prep_questions", vacancy_id="missing"), account=caller
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "Вакансия не найдена"
    assert await runtime.list_recent() == []


@pytest.mark.asyncio
async def test_push_enqueues_when_linked_and_job_exists(
    settings_store: dict[str, Any],
    accounts: FakeAccountsStore,
    monkeypatch: pytest.MonkeyPatch,
    runtime,
) -> None:
    from api.routers.meta import telegram as api_tg
    from api.schemas.telegram import TelegramPushRequest

    await _link_owner()
    monkeypatch.setattr(api_tg, "get_job_by_vacancy_id", AsyncMock(return_value=object()))

    resp = await api_tg.enqueue_push_response(
        TelegramPushRequest(kind="offer_summary", vacancy_id="  hh:99  "), account=_OWNER_CTX
    )
    assert resp.queued is True
    assert resp.kind == "offer_summary"
    assert resp.vacancy_id == "hh:99"
    assert resp.task_id > 0

    rows = await runtime.list_recent()
    assert len(rows) == 1
    assert rows[0].kind == tp.TG_PUSH_KIND
    assert rows[0].payload == {"kind": "offer_summary", "vacancy_id": "hh:99", "account_id": 1}
    assert rows[0].account_id == 1
    assert rows[0].id == resp.task_id


@pytest.mark.asyncio
async def test_push_uses_callers_own_account_not_owner(
    settings_store: dict[str, Any],
    accounts: FakeAccountsStore,
    monkeypatch: pytest.MonkeyPatch,
    runtime,
) -> None:
    """M7: member со своей вакансией пушит успешно и на СВОЙ аккаунт, не на владельца
    (plans/multitenancy_gaps_2026_08_06.md §3.11 — раньше валидация шла по `tg.get_owner()`)."""
    from api.routers.meta import telegram as api_tg
    from api.schemas.telegram import TelegramPushRequest

    await _link_owner(user_id=1, chat_id=1)  # владелец account_id=1
    member = await tl.consume_token(
        (await tl.create_link_token()).token, user_id=2, chat_id=2, role="member"
    )
    assert member is not None and member.id != 1

    seen_account_ids: list[int | None] = []

    async def fake_get_job(vacancy_id: str, *, account_id: int | None = None) -> Any:
        seen_account_ids.append(account_id)
        return _job(vacancy_id=vacancy_id) if account_id == member.id else None

    monkeypatch.setattr(api_tg, "get_job_by_vacancy_id", fake_get_job)
    member_ctx = AccountContext(
        account_id=member.id, telegram_user_id=2, telegram_username=None, role="member"
    )

    resp = await api_tg.enqueue_push_response(
        TelegramPushRequest(kind="vacancy_card", vacancy_id="hh:1"), account=member_ctx
    )
    assert resp.queued is True
    assert seen_account_ids == [member.id]

    rows = await runtime.list_recent()
    assert rows[0].payload["account_id"] == member.id


@pytest.mark.asyncio
async def test_api_push_double_click_same_task_id(
    settings_store: dict[str, Any],
    accounts: FakeAccountsStore,
    monkeypatch: pytest.MonkeyPatch,
    runtime,
) -> None:
    """Даблклик «В Telegram» в ту же минуту → один task_id (идемпотентность API)."""
    from api.routers.meta import telegram as api_tg
    from api.schemas.telegram import TelegramPushRequest

    await _link_owner()
    monkeypatch.setattr(api_tg, "get_job_by_vacancy_id", AsyncMock(return_value=object()))
    fixed = datetime(2026, 7, 31, 10, 5, 12, tzinfo=UTC)
    real_enqueue = tp.enqueue_tg_push

    async def enqueue_fixed(kind, vacancy_id, *, account_id, at=None):
        _ = at
        return await real_enqueue(kind, vacancy_id, account_id=account_id, at=fixed)

    monkeypatch.setattr(tp, "enqueue_tg_push", enqueue_fixed)
    # Роутер импортировал модуль как tg_push — тот же объект, что `tp`.
    assert api_tg.tg_push is tp

    body = TelegramPushRequest(kind="vacancy_card", vacancy_id="hh:7")
    first = await api_tg.enqueue_push_response(body, account=_OWNER_CTX)
    second = await api_tg.enqueue_push_response(body, account=_OWNER_CTX)
    assert first.task_id == second.task_id
    assert len(await runtime.list_recent()) == 1


# --- рендер текстов по фикстурам -----------------------------------------------------------------


def test_format_screening_push_with_pack() -> None:
    from bot_app.services.push_handler import format_screening_push
    from core.domains.preparation.screening_questions import SavedScreeningQuestions

    pack = SavedScreeningQuestions(
        vacancy_id="hh:1",
        oral_pitch="Я делал X и Y <script>",
        why_company="Продукт нравится",
        hr_questions=[
            {"question": "Почему мы?"},
            {"question": "Опыт?"},
            {"question": "Зарплата?"},
            {"question": "лишний"},
        ],
    )
    msg = format_screening_push(
        pack,
        vacancy_id="hh:1",
        job=_job(),
        web_url="https://app.example",
    )
    assert "Скрининг" in msg.text
    assert "Acme — PM" in msg.text
    assert "Я делал X и Y &lt;script&gt;" in msg.text
    assert "Почему мы?" in msg.text
    assert "лишний" not in msg.text
    assert msg.reply_markup is not None
    btn = msg.reply_markup.inline_keyboard[0][0]
    assert btn.url == "https://app.example/screening?vacancy=hh:1"
    assert btn.text == "Открыть скрининг"


def test_format_screening_push_empty_no_https_button() -> None:
    from bot_app.services.push_handler import format_screening_push

    msg = format_screening_push(
        None,
        vacancy_id="hh:1",
        web_url="http://localhost:5173",
    )
    assert "ещё не собран" in msg.text
    assert msg.reply_markup is None


def test_format_prep_push_questions() -> None:
    from bot_app.services.push_handler import format_prep_push

    msg = format_prep_push(
        [
            {"text": "Что такое CAP?"},
            {"text": "Расскажи про Kafka"},
            {"text": ""},
        ],
        vacancy_id="hh:1",
        stage="tech",
        job=_job(),
        web_url="https://app.example",
    )
    assert "Техничка" in msg.text
    assert "Этап: Техничка" in msg.text
    assert "CAP" in msg.text
    assert "Kafka" in msg.text
    assert msg.reply_markup is not None
    assert msg.reply_markup.inline_keyboard[0][0].url == (
        "https://app.example/tech?vacancy=hh:1"
    )


def test_format_prep_push_empty() -> None:
    from bot_app.services.push_handler import format_prep_push

    msg = format_prep_push(
        [],
        vacancy_id="hh:1",
        stage="system_design",
        job=_job(company="Gamma", title="Architect"),
        web_url="https://app.example",
    )
    assert "Gamma — Architect" in msg.text
    assert "System design" in msg.text
    assert "нет" in msg.text.lower()
    assert msg.reply_markup is not None


def test_format_offer_push_compact() -> None:
    from bot_app.services.push_handler import format_offer_push
    from core.domains.offers.store import Offer

    offer = Offer(
        vacancy_id="hh:1",
        company="Beta",
        position="Lead",
        base_salary=400_000,
        base_salary_currency="RUB",
        base_salary_period="month",
        base_salary_tax_basis="net",
        work_format="hybrid",
        status="thinking",
        notes="Жду ответа HR",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        updated_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    msg = format_offer_push(
        offer,
        vacancy_id="hh:1",
        web_url="https://app.example",
    )
    assert "Оффер" in msg.text
    assert "Beta — Lead" in msg.text
    assert "400 000 RUB/мес" in msg.text
    assert "гибрид" in msg.text
    assert "думаю" in msg.text
    assert "Сравнение с другими" in msg.text
    assert msg.reply_markup is not None
    assert msg.reply_markup.inline_keyboard[0][0].url == "https://app.example/offers"


def test_format_offer_push_missing() -> None:
    from bot_app.services.push_handler import format_offer_push

    msg = format_offer_push(
        None,
        vacancy_id="hh:1",
        job=_job(),
        web_url="https://app.example",
    )
    assert "ещё не сохранён" in msg.text
    assert msg.reply_markup is not None
    assert msg.reply_markup.inline_keyboard[0][0].url == "https://app.example/offers"


# --- handler: мок отправки --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_tg_push_skips_without_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot_app.services import push_handler as ph

    monkeypatch.setattr(ph, "_BOT", None)
    called = {"n": 0}

    async def boom() -> int | None:
        called["n"] += 1
        raise AssertionError("не должно вызываться")

    monkeypatch.setattr(ph, "push_chat_id", boom)
    await ph.handle_tg_push({"kind": "vacancy_card", "vacancy_id": "hh:1"})
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_handle_tg_push_skips_without_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot_app.services import push_handler as ph

    monkeypatch.setattr(ph, "_BOT", AsyncMock())
    monkeypatch.setattr(ph, "push_chat_id", AsyncMock(return_value=None))
    dispatch = AsyncMock()
    monkeypatch.setattr(ph, "_dispatch", dispatch)
    await ph.handle_tg_push({"kind": "screening_pack", "vacancy_id": "hh:1"})
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_tg_push_screening_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot_app.services import push_handler as ph
    from core.domains.preparation.screening_questions import SavedScreeningQuestions

    bot = AsyncMock()
    monkeypatch.setattr(ph, "_BOT", bot)
    monkeypatch.setattr(ph, "push_chat_id", AsyncMock(return_value=7))
    monkeypatch.setattr(ph, "_load_job", AsyncMock(return_value=_job()))
    monkeypatch.setattr(
        "bot_app.access.resolve_owner_account_id", AsyncMock(return_value=1)
    )
    monkeypatch.setattr(
        ph,
        "get_screening_questions",
        AsyncMock(
            return_value=SavedScreeningQuestions(
                vacancy_id="hh:1",
                oral_pitch="Питч",
                hr_questions=[{"question": "Почему?"}],
            )
        ),
    )
    sent: list[dict[str, Any]] = []

    async def capture_send(_b, chat_id, text, **kwargs):
        sent.append({"chat_id": chat_id, "text": text, **kwargs})
        return AsyncMock()

    monkeypatch.setattr(ph, "safe_send", capture_send)
    monkeypatch.setattr(ph, "show_menu", AsyncMock())
    monkeypatch.setattr(
        "bot_app.services.push_handler.get_bot_settings",
        lambda: type("S", (), {"web_url": "https://app.example"})(),
    )

    await ph.handle_tg_push({"kind": "screening_pack", "vacancy_id": "hh:1"})
    assert len(sent) == 1
    assert sent[0]["chat_id"] == 7
    assert "Питч" in sent[0]["text"]
    assert "Почему?" in sent[0]["text"]
    assert sent[0]["reply_markup"] is not None
    ph.show_menu.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_tg_push_prep_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot_app.services import push_handler as ph
    from core.domains.preparation.prep import PrepSession

    bot = AsyncMock()
    monkeypatch.setattr(ph, "_BOT", bot)
    monkeypatch.setattr(ph, "push_chat_id", AsyncMock(return_value=11))
    monkeypatch.setattr(ph, "_load_job", AsyncMock(return_value=_job()))
    monkeypatch.setattr(
        "bot_app.access.resolve_owner_account_id", AsyncMock(return_value=1)
    )
    monkeypatch.setattr(
        ph,
        "load_prep_history",
        AsyncMock(
            return_value=[
                PrepSession(
                    vacancy_id="hh:1",
                    stage="tech",
                    questions=[{"text": "Что такое CAP theorem?"}],
                    status="generated",
                )
            ]
        ),
    )
    sent: list[dict[str, Any]] = []

    async def capture_send(_b, chat_id, text, **kwargs):
        sent.append({"chat_id": chat_id, "text": text, **kwargs})
        return AsyncMock()

    monkeypatch.setattr(ph, "safe_send", capture_send)
    monkeypatch.setattr(ph, "show_menu", AsyncMock())
    monkeypatch.setattr(
        "bot_app.services.push_handler.get_bot_settings",
        lambda: type("S", (), {"web_url": "https://app.example"})(),
    )

    await ph.handle_tg_push({"kind": "prep_questions", "vacancy_id": "hh:1"})
    assert len(sent) == 1
    assert "CAP theorem" in sent[0]["text"]
    assert "Техничка" in sent[0]["text"]
    assert sent[0]["reply_markup"].inline_keyboard[0][0].url.endswith(
        "/tech?vacancy=hh:1"
    )


@pytest.mark.asyncio
async def test_handle_tg_push_offer_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot_app.services import push_handler as ph
    from core.domains.offers.store import Offer

    offer = Offer(
        vacancy_id="hh:1",
        company="Delta",
        position="Staff",
        base_salary=500_000,
        base_salary_currency="RUB",
        base_salary_period="month",
        work_format="remote",
        status="thinking",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        updated_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    bot = AsyncMock()
    monkeypatch.setattr(ph, "_BOT", bot)
    monkeypatch.setattr(ph, "push_chat_id", AsyncMock(return_value=13))
    monkeypatch.setattr(ph, "_load_job", AsyncMock(return_value=_job()))
    monkeypatch.setattr(ph, "_load_offer", AsyncMock(return_value=offer))
    sent: list[dict[str, Any]] = []

    async def capture_send(_b, chat_id, text, **kwargs):
        sent.append({"chat_id": chat_id, "text": text, **kwargs})
        return AsyncMock()

    monkeypatch.setattr(ph, "safe_send", capture_send)
    monkeypatch.setattr(ph, "show_menu", AsyncMock())
    monkeypatch.setattr(
        "bot_app.services.push_handler.get_bot_settings",
        lambda: type("S", (), {"web_url": "https://app.example"})(),
    )

    await ph.handle_tg_push({"kind": "offer_summary", "vacancy_id": "hh:1"})
    assert len(sent) == 1
    assert "Delta — Staff" in sent[0]["text"]
    assert "500 000" in sent[0]["text"]
    assert sent[0]["reply_markup"].inline_keyboard[0][0].url.endswith("/offers")


@pytest.mark.asyncio
async def test_handle_tg_push_vacancy_card_uses_score_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bot_app.services import push_handler as ph
    from core.domains.opportunities.models import (
        BurnoutRisk,
        GradeMatch,
        RemoteAbroadCompat,
        RoleContentMatch,
        SalaryInfo,
        ScoreResult,
    )

    score = ScoreResult(
        overall_score=80,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="300k", note=""),
        role_content_match=RoleContentMatch(score=80, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["p"],
        cons=["c"],
        red_flags=[],
        one_line_verdict="ok",
    )
    job = _job(score=score.model_dump())

    bot = AsyncMock()
    monkeypatch.setattr(ph, "_BOT", bot)
    monkeypatch.setattr(ph, "push_chat_id", AsyncMock(return_value=9))
    monkeypatch.setattr(ph, "_load_job", AsyncMock(return_value=job))
    send_card = AsyncMock()
    monkeypatch.setattr(ph, "send_or_replace_score_card", send_card)
    monkeypatch.setattr(ph, "show_menu", AsyncMock())

    await ph.handle_tg_push({"kind": "vacancy_card", "vacancy_id": "hh:1"})
    send_card.assert_awaited_once()
    assert send_card.await_args.kwargs["header"] == "Из веба"
    assert send_card.await_args.kwargs["job"].vacancy_id == "hh:1"
    ph.show_menu.assert_awaited_once()


def test_register_tg_push_registers_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot_app.services import push_handler as ph

    runtime = reset_runtime_for_tests(MemoryTaskStore())
    registered: list[str] = []
    real = runtime.register_handler

    def track(kind: str, handler):
        registered.append(kind)
        return real(kind, handler)

    monkeypatch.setattr(
        "core.platform.tasks.register_handler",
        lambda kind, handler: track(kind, handler),
    )
    ph.register_tg_push(MagicMock())
    assert tp.TG_PUSH_KIND in registered
    assert ph._BOT is not None
