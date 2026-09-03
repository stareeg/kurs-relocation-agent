# kernel

Общие доменные примитивы без I/O.

- `text/` — анти-slop линтер (`style_lint`)
- `money.py` — валюта, период, gross→net
- `ports.py` — **порты инфраструктуры**: `LlmPort`, `CachePort`, `Clock`,
  `EventBus`, `VacancySource`, `Channel`, `Notifier` + реестр (`bind` / `use_ports` / аксессоры)
- `vacancy.py` — `RawVacancy` (контракт выхода `VacancySource` до скоринга)
- `errors.py` — `DomainError`, `LlmError`, `PortNotBoundError` (маппинг в HTTP — A-15)
- `ids.py` / `events.py` — контракты (наполнение в треке A)

Импортирует только stdlib и pydantic. Реализации портов живут в `core/app/wiring.py`.

## Порты в домене

```python
from core.kernel import ports

async def assess(text: str, *, llm: ports.LlmPort | None = None) -> Verdict:
    port = llm or ports.llm()          # прод — связанный порт, тест — фейк параметром
    return await port.structured("feature_name", schema=Verdict, user=text)
```

Тир, промпт и бюджет берутся из `LlmFeature` по имени фичи (`domains/*/llm.py`) — домен
не знает ни про langchain, ни про OpenRouter. Сбой провайдера/таймаут приходит как `LlmError`.
В тестах: параметр `llm=` либо `with ports.use_ports(llm=FakeLlm()): ...`.
