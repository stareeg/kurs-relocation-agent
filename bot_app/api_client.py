"""HTTP-клиент бота к API.

Все запросы несут X-API-Key (тот же ключ, что у расширения). Покрывает то, что нужно
каналу бота: метрики (cost-алёрт), синхронный скоринг и health.
HITL / tasks удалены в R-12 / R-14.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from bot_app.config import BotSettings, get_bot_settings

logger = logging.getLogger(__name__)


class CopilotApiClient:
    """Тонкая обёртка над httpx к API. Один на процесс; транспорт инъектируется в тестах."""

    def __init__(
        self,
        settings: BotSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_bot_settings()
        headers = {}
        if self._settings.api_key:
            headers["X-API-Key"] = self._settings.api_key
        self._client = httpx.AsyncClient(
            base_url=self._settings.backend_url.rstrip("/"),
            headers=headers,
            timeout=self._settings.api_timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        resp = await self._client.get("/health", timeout=10)
        resp.raise_for_status()
        return resp.json()

    async def metrics(self) -> dict[str, Any]:
        """GET /api/metrics — агрегаты стоимости (today_cost_usd для cost-алёрта)."""
        resp = await self._client.get("/api/metrics")
        resp.raise_for_status()
        return resp.json()

    async def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /score — синхронный скоринг вакансии (тот же контракт, что у расширения)."""
        resp = await self._client.post("/score", json=payload)
        resp.raise_for_status()
        return resp.json()
