"""İlk yanıt süresine ilişkin bağımsız iş kuralları."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any


# ============================================================
# 2. POLİTİKA VE HEDEF SÜRELER
# ============================================================

POLICY_VERSION = "first-response-v1"

FIRST_RESPONSE_TARGET_SECONDS = {
    "HIGH": 60 * 60,
    "NORMAL": 8 * 60 * 60,
    "LOW": 24 * 60 * 60,
}


class SlaStatus(StrEnum):
    """İlk yanıt hedefinin değerlendirme sonucu."""

    NOT_TRACKED = "NOT_TRACKED"
    WAITING = "WAITING"
    BREACHED = "BREACHED"
    MET = "MET"
    MISSED = "MISSED"


# ============================================================
# 3. TALEP AÇILIRKEN POLİTİKANIN KOPYASINI AL
# ============================================================

def make_policy_snapshot(priority: str) -> dict[str, str | int]:
    """Talebe uygulanacak hedefi oluşturulma anında sabitler."""

    if priority not in FIRST_RESPONSE_TARGET_SECONDS:
        raise ValueError(f"Desteklenmeyen öncelik: {priority}")

    return {
        "policy_version": POLICY_VERSION,
        "target_seconds": FIRST_RESPONSE_TARGET_SECONDS[priority],
    }


# ============================================================
# 4. ZAMAN DEĞERLERİNİ UTC'YE DÖNÜŞTÜR
# ============================================================

def _as_utc(value: datetime) -> datetime:
    """Saat dilimi olmayan tarihleri reddeder."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("SLA hesabında saat dilimi olan datetime gerekir.")

    return value.astimezone(timezone.utc)


# ============================================================
# 5. İLK YANIT HEDEFİNİ DEĞERLENDİR
# ============================================================

def evaluate_first_response(
    *,
    created_at: datetime,
    target_seconds: int | None,
    policy_version: str | None,
    first_response_at: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    """
    İlk yanıt hedefini değerlendirir.

    Fonksiyon veritabanına bağlanmaz ve kendi saatini okumaz.
    'now' dışarıdan verildiği için beklemeden sınır testleri yazılabilir.
    """

    started_at = _as_utc(created_at)
    evaluated_at = _as_utc(now)

    result = {
        "status": SlaStatus.NOT_TRACKED,
        "policy_version": policy_version,
        "target_seconds": target_seconds,
        "started_at": started_at,
        "due_at": None,
        "first_response_at": None,
        "evaluated_at": evaluated_at,
    }

    # Eski taleplerde politika kaydı bulunmayabilir.
    # Böyle bir durumda geçmişe dönük bir hedef uydurmayız.
    if target_seconds is None:
        return result

    if type(target_seconds) is not int or target_seconds <= 0:
        raise ValueError("Hedef süre pozitif bir tam sayı olmalıdır.")

    due_at = started_at + timedelta(seconds=target_seconds)
    result["due_at"] = due_at

    if first_response_at is not None:
        response_at = _as_utc(first_response_at)

        if response_at < started_at:
            raise ValueError("İlk yanıt, talep oluşturulmadan önce olamaz.")

        result["first_response_at"] = response_at

        # Tam son tarihte verilen yanıtı zamanında kabul ediyoruz.
        result["status"] = (
            SlaStatus.MET
            if response_at <= due_at
            else SlaStatus.MISSED
        )
    else:
        result["status"] = (
            SlaStatus.BREACHED
            if evaluated_at > due_at
            else SlaStatus.WAITING
        )

    return result