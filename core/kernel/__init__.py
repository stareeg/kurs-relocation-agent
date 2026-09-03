"""Общие доменные примитивы без I/O: текст, деньги, ids, порты, события, UoW."""

from core.kernel.errors import DomainError, LlmError, PortNotBoundError
from core.kernel.ids import (
    ApplicationId,
    ConversationId,
    InterviewId,
    OfferId,
    ResumeVersionId,
    VacancyId,
)
from core.kernel.money import GROSS_TO_NET_RATIO, gross_to_net, to_monthly, to_net
from core.kernel.uow import UnitOfWork

__all__ = [
    "ApplicationId",
    "ConversationId",
    "DomainError",
    "GROSS_TO_NET_RATIO",
    "InterviewId",
    "LlmError",
    "OfferId",
    "PortNotBoundError",
    "ResumeVersionId",
    "UnitOfWork",
    "VacancyId",
    "gross_to_net",
    "to_monthly",
    "to_net",
]
