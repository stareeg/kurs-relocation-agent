"""LLM-фичи домена assistant (реестр LlmFeature — A-06/A-09)."""

from __future__ import annotations

from core.platform.llm.registry import LlmFeature, register

CHAT_SYSTEM = "prompts/assistant/system.md"
ATTACHMENT_READ_PROMPT = "prompts/assistant/attachment_read.md"
RESUME_GAP_CHAT_PROMPT = "prompts/assistant/resume_gap_chat.md"
ADMIN_SUPPORT_PROMPT = "prompts/assistant/admin_support.md"

CHAT = register(
    LlmFeature(
        name="chat",
        tier="basic",
        prompt=CHAT_SYSTEM,
        cache_prefix=True,
        temperature=0.6,
        max_tokens=4096,
        budget_ms=45_000,
        retries=1,
    )
)
# Режимы стрима в service.py (раньше — сырой тир reasoning через get_chat_model).
QA_VACANCY = register(
    LlmFeature(
        name="qa_vacancy",
        tier="advanced",
        temperature=0.4,
        max_tokens=4096,
        budget_ms=75_000,
        retries=1,
        prompt_in_code=True,
        cache_prefix=True,  # L-11: qa-base статичен, вакансия — dynamic_tail
    )
)
RESUME_GAP_CHAT = register(
    LlmFeature(
        name="resume_gap_chat",
        tier="reserve",
        prompt=RESUME_GAP_CHAT_PROMPT,
        temperature=0.4,
        max_tokens=4096,
        budget_ms=75_000,
        retries=1,
        cache_prefix=True,  # L-11: static system + dynamic_tail (факторы/опыт/рынок)
    )
)
HR_DRAFT_CHAT = register(
    LlmFeature(
        name="hr_draft_chat",
        tier="advanced",
        temperature=0.5,
        max_tokens=4096,
        budget_ms=75_000,
        retries=1,
        prompt_in_code=True,
        cache_prefix=True,  # L-11
    )
)
CHAT_FOLLOWUPS = register(
    LlmFeature(
        name="chat_followups",
        tier="basic",
        temperature=0.4,
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
# Фоновое распознавание вложений:
# tier=basic — быстро и дёшево, vision умеет (проверено вживую);
# reasoning_effort не задан — это распознавание, а не рассуждение.
ATTACHMENT_READ = register(
    LlmFeature(
        name="attachment_read",
        tier="basic",
        prompt=ATTACHMENT_READ_PROMPT,
        temperature=0.0,
        max_tokens=4096,  # ≥1024; скрин длинной переписки — это много текста
        budget_ms=45_000,
        retries=1,
    )
)
# Черновик оператора в карточке человека: человек эти реплики не видит.
ADMIN_SUPPORT = register(
    LlmFeature(
        name="admin_support",
        tier="basic",
        prompt=ADMIN_SUPPORT_PROMPT,
        temperature=0.3,
        max_tokens=2048,
        budget_ms=45_000,
        retries=1,
        cache_prefix=True,
    )
)

FEATURES: tuple[LlmFeature, ...] = (
    CHAT,
    QA_VACANCY,
    RESUME_GAP_CHAT,
    HR_DRAFT_CHAT,
    CHAT_FOLLOWUPS,
    ATTACHMENT_READ,
    ADMIN_SUPPORT,
)

PROMPT_PATHS: dict[str, str] = {
    "chat_system": CHAT_SYSTEM,
    "attachment_read": ATTACHMENT_READ_PROMPT,
    "resume_gap_chat": RESUME_GAP_CHAT_PROMPT,
    "admin_support": ADMIN_SUPPORT_PROMPT,
}

__all__ = [
    "FEATURES",
    "CHAT_SYSTEM",
    "CHAT",
    "QA_VACANCY",
    "RESUME_GAP_CHAT",
    "HR_DRAFT_CHAT",
    "RESUME_GAP_CHAT_PROMPT",
    "CHAT_FOLLOWUPS",
    "ATTACHMENT_READ_PROMPT",
    "ATTACHMENT_READ",
    "ADMIN_SUPPORT",
    "ADMIN_SUPPORT_PROMPT",
    "PROMPT_PATHS",
]
