# ============================================================
# İÇE AKTARMALAR
# ============================================================

from sqlalchemy import Select, or_, select

from app.models import TeamMember, Ticket, User, UserRole


# ============================================================
# KULLANICININ GÖREBİLECEĞİ TALEPLER
# ============================================================

def visible_tickets_query(current_user: User) -> Select[tuple[Ticket]]:
    """
    Kullanıcının görebileceği talepleri seçen SQL sorgusunu oluşturur.

    Bu fonksiyon sorguyu çalıştırmaz. Endpoint, sorguya filtre veya
    talep kimliği ekleyip veritabanı oturumunda çalıştırır.
    """

    statement = select(Ticket)

    # --------------------------------------------------------
    # 1. Yönetici bütün talepleri görebilir
    # --------------------------------------------------------

    if current_user.role == UserRole.MANAGER:
        return statement

    # --------------------------------------------------------
    # 2. Her kullanıcı kendi taleplerini görebilir
    # --------------------------------------------------------

    owns_ticket = Ticket.requester_id == current_user.id

    # --------------------------------------------------------
    # 3. Görevli, üyesi olduğu ekiplerin taleplerini de görebilir
    # --------------------------------------------------------

    if current_user.role == UserRole.AGENT:
        belongs_to_ticket_team = (
            select(TeamMember.user_id)
            .where(
                TeamMember.team_id == Ticket.team_id,
                TeamMember.user_id == current_user.id,
            )
            .exists()
        )

        return statement.where(
            or_(
                owns_ticket,
                belongs_to_ticket_team,
            )
        )

    # --------------------------------------------------------
    # 4. Talep sahibi rolü yalnızca kendi kayıtlarını görür
    # --------------------------------------------------------

    return statement.where(owns_ticket)