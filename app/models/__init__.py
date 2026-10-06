"""Uygulamanın veritabanı modellerini ortak noktadan dışarı açar."""

# ============================================================
# 1. MODELLERİ YÜKLE
# ============================================================

from app.models.base import Base
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.ticket import Ticket, TicketPriority, TicketStatus
from app.models.ticket_comment import TicketComment
from app.models.ticket_event import TicketEvent, TicketEventType
from app.models.user import User, UserRole


# ============================================================
# 2. DIŞARIYA AÇILAN MODEL ADLARI
# ============================================================

__all__ = [
    "Base",
    "Team",
    "TeamMember",
    "Ticket",
    "TicketPriority",
    "TicketStatus",
    "TicketComment",
    "TicketEvent",
    "TicketEventType",
    "User",
    "UserRole",
]