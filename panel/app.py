"""Servis Takip'in mevcut HTTP API'sini kullanan bağımsız web paneli."""

# ============================================================================
# 1. KÜTÜPHANELER VE EKRANDA KULLANILAN ADLAR
# ============================================================================
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import streamlit as st

API_URL = os.getenv("SERVIS_API_URL", "http://127.0.0.1:8000").rstrip("/")
STATUS = {"OPEN": "Açık", "IN_PROGRESS": "İşlemde", "RESOLVED": "Çözüldü"}
PRIORITY = {"LOW": "Düşük", "NORMAL": "Normal", "HIGH": "Yüksek"}
ROLES = {"manager": "Yönetici", "agent": "Servis görevlisi", "requester": "Talep sahibi"}
SLA = {
    "NOT_TRACKED": "Takip edilmiyor", "WAITING": "Yanıt bekleniyor",
    "BREACHED": "Yanıt süresi aşıldı", "MET": "Zamanında yanıtlandı",
    "MISSED": "Geç yanıtlandı",
}
EVENTS = {
    "CREATED": "Talep oluşturuldu", "CLAIMED": "Talep üstlenildi",
    "COMMENT_ADDED": "Yorum eklendi", "RESOLVED": "Talep çözüldü",
    "REOPENED": "Talep yeniden açıldı",
}


# ============================================================================
# 2. API İLETİŞİMİ VE OTURUM YÖNETİMİ
# ============================================================================
class ApiError(Exception):
    """İstek başarısız olduğunda kullanıcıya gösterilecek kontrollü hata."""


def clear_session(message=None):
    """Önceki kullanıcıya ait token, seçim ve form durumlarını kaldırır."""
    st.session_state.clear()
    if message:
        st.session_state["notice"] = message


def api(method, path, *, authenticated=True, **kwargs):
    """Tokenı yalnızca bu tarayıcı oturumundan alır; ortak cache kullanmaz."""
    headers = {}
    if authenticated:
        token = st.session_state.get("token")
        if not token:
            clear_session("Devam etmek için giriş yapmalısın.")
            st.rerun()
        headers["Authorization"] = f"Bearer {token}"
    try:
        # Yazma isteklerini otomatik tekrarlamıyoruz: çift kayıt oluşabilir.
        response = httpx.request(
            method, API_URL + path, headers=headers,
            timeout=15.0, follow_redirects=False, **kwargs,
        )
    except httpx.RequestError:
        raise ApiError(
            "API yanıtına ulaşılamadı. API'nin çalıştığını kontrol et. "
            "Bir kayıt işlemi yaptıysan yeniden göndermeden önce listeyi yenile; "
            "işlem sunucuda tamamlanmış olabilir."
        ) from None

    if response.status_code == 401 and authenticated:
        clear_session("Oturumun sona erdi veya hesap kullanılamıyor. Yeniden giriş yap.")
        st.rerun()

    if response.is_error or response.is_redirect:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if response.status_code >= 500:
            message = "Sunucu işlemi tamamlayamadı."
        elif isinstance(detail, list):
            # Doğrulama hatalarındaki giriş değerlerini/parolayı ekrana basma.
            message = " | ".join(
                f"{'.'.join(map(str, item.get('loc', [])))}: {item.get('msg', 'Geçersiz değer')}"
                for item in detail if isinstance(item, dict)
            )
        elif isinstance(detail, str):
            message = detail
        else:
            message = "İstek tamamlanamadı."
        request_id = response.headers.get("X-Request-ID")
        suffix = f" İstek kimliği: {request_id}" if request_id else ""
        raise ApiError(f"{message} (HTTP {response.status_code}){suffix}")

    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError:
        raise ApiError("API'den beklenen veri biçimi alınamadı.") from None


def success(message, screen=None):
    """Yazma işleminden sonra verileri API'den yeniden yükletir."""
    st.session_state["notice"] = message
    if screen:
        st.session_state["next_screen"] = screen
    st.rerun()


def time_label(value):
    if not value:
        return "—"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        ZoneInfo("Europe/Istanbul")
    ).strftime("%d.%m.%Y %H:%M")


def all_rows(path):
    """Liste döndüren ekip/üyelik endpoint'lerinde bütün sayfaları okur."""
    result = []
    while True:
        page = api("GET", path, params={"limit": 100, "offset": len(result)})
        result.extend(page)
        if len(page) < 100:
            return result


# ============================================================================
# 3. GİRİŞ VE TALEP SAHİBİ KAYDI
# ============================================================================
def account_fields(prefix):
    name = st.text_input("Ad soyad", max_chars=100, key=f"{prefix}_name")
    email = st.text_input("E-posta", max_chars=254, key=f"{prefix}_email")
    password = st.text_input("Parola", type="password", max_chars=128, key=f"{prefix}_password")
    repeat = st.text_input("Parola tekrar", type="password", max_chars=128, key=f"{prefix}_repeat")
    st.caption("Parola 15–128 karakter olmalı.")
    return name, email, password, repeat


def account_payload(fields):
    name, email, password, repeat = fields
    if password != repeat:
        raise ApiError("Parolalar eşleşmiyor.")
    if not 15 <= len(password) <= 128:
        raise ApiError("Parola 15–128 karakter olmalı.")
    return {"full_name": name.strip(), "email": email.strip(), "password": password}


def login_page():
    st.title("Servis Takip")
    st.write("Taleplerini oluştur, ilerlemeyi takip et ve ekibinle iletişim kur.")
    login_tab, register_tab = st.tabs(["Giriş yap", "Talep sahibi hesabı oluştur"])
    with login_tab:
        with st.form("login", clear_on_submit=True):
            email = st.text_input("E-posta", key="login_email")
            password = st.text_input("Parola", type="password", key="login_password")
            submitted = st.form_submit_button("Giriş yap", type="primary")
        if submitted:
            result = api("POST", "/auth/token", authenticated=False,
                         data={"username": email.strip(), "password": password})
            clear_session()
            st.session_state["token"] = result["access_token"]
            st.rerun()
    with register_tab:
        with st.form("registration", clear_on_submit=True):
            fields = account_fields("register")
            submitted = st.form_submit_button("Hesap oluştur")
        if submitted:
            api("POST", "/users", authenticated=False, json=account_payload(fields))
            success("Hesabın oluşturuldu. E-posta ve parolanla giriş yapabilirsin.")


# ============================================================================
# 4. ÖZET EKRANI
# ============================================================================
def overview():
    st.title("Genel bakış")
    st.caption("Rakamlar yalnızca görme yetkin olan talepleri kapsar.")
    report = api("GET", "/reports/tickets/summary")
    counts = {row["status"]: row["count"] for row in report["by_status"]}
    columns = st.columns(4)
    columns[0].metric("Toplam talep", report["total"])
    for column, (code, label) in zip(columns[1:], STATUS.items()):
        column.metric(label, counts.get(code, 0))
    left, right = st.columns(2)
    with left:
        st.subheader("Öncelikler")
        st.dataframe([{"Öncelik": PRIORITY[r["priority"]], "Talep": r["count"]}
                      for r in report["by_priority"]], hide_index=True, width="stretch")
    with right:
        st.subheader("İlk yanıt süreleri")
        st.dataframe([{"Durum": SLA[r["status"]], "Talep": r["count"]}
                      for r in report["by_sla"]], hide_index=True, width="stretch")
    st.caption(f"Hesaplama zamanı: {time_label(report['evaluated_at'])}")


# ============================================================================
# 5. TALEP LİSTESİ VE YENİ TALEP
# ============================================================================
def reset_ticket_page():
    st.session_state["ticket_page"] = 1


def tickets_page(teams):
    st.title("Talepler")
    a, b, c = st.columns(3)
    status = a.selectbox("Durum", [None, *STATUS],
                        format_func=lambda x: STATUS.get(x, "Tümü"), on_change=reset_ticket_page)
    priority = b.selectbox("Öncelik", [None, *PRIORITY],
                          format_func=lambda x: PRIORITY.get(x, "Tümü"), on_change=reset_ticket_page)
    names = {t["id"]: t["name"] for t in teams}
    team = c.selectbox("Ekip", [None, *names],
                       format_func=lambda x: names.get(x, "Tümü"), on_change=reset_ticket_page)
    page = int(st.number_input("Sayfa", min_value=1, step=1, key="ticket_page"))
    params = {"limit": 20, "offset": (page - 1) * 20}
    params.update({k: v for k, v in {"status": status, "priority": priority, "team_id": team}.items() if v is not None})
    result = api("GET", "/tickets", params=params)
    st.caption(f"{result['total']} kayıt · Sayfa {page} / {max(1, (result['total'] + 19) // 20)}")
    if not result["items"]:
        st.info("Bu sayfada talep yok. Filtreleri veya sayfa numarasını değiştirebilirsin.")
        return
    st.dataframe([{
        "No": t["id"], "Başlık": t["title"], "Durum": STATUS[t["status"]],
        "Öncelik": PRIORITY[t["priority"]], "Ekip": names.get(t["team_id"], str(t["team_id"])),
        "Oluşturulma": time_label(t["created_at"]),
    } for t in result["items"]], hide_index=True, width="stretch")
    choices = {t["id"]: f"#{t['id']} · {t['title']}" for t in result["items"]}
    selected = st.selectbox("Ayrıntısını açacağın talep", choices, format_func=choices.get)
    if st.button("Talebi aç", type="primary"):
        st.session_state["detail_id"] = selected
        st.session_state["next_screen"] = "Talep ayrıntısı"
        st.rerun()


def new_ticket(teams):
    st.title("Yeni talep")
    active = {t["id"]: t["name"] for t in teams if t["is_active"]}
    if not active:
        st.info("Aktif ekip yok. Yönetici önce bir ekip oluşturmalı veya aktifleştirmeli.")
        return
    with st.form("new_ticket"):
        title = st.text_input("Başlık", max_chars=150)
        description = st.text_area("Sorunu ayrıntılı açıkla", max_chars=5000, height=160)
        team = st.selectbox("İlgili ekip", active, format_func=active.get)
        priority = st.selectbox("Öncelik", list(PRIORITY), index=1, format_func=PRIORITY.get)
        submitted = st.form_submit_button("Talep oluştur", type="primary")
    if submitted:
        result = api("POST", "/tickets", json={
            "title": title, "description": description, "team_id": team, "priority": priority,
        })
        st.session_state["detail_id"] = result["id"]
        success(f"#{result['id']} numaralı talep oluşturuldu.", "Talep ayrıntısı")


# ============================================================================
# 6. TALEP AYRINTISI, YORUMLAR VE GEÇMİŞ
# ============================================================================
def ticket_detail(user, teams):
    st.title("Talep ayrıntısı")
    ticket_id = int(st.number_input("Talep numarası", min_value=1, max_value=2147483647,
                                    step=1, key="detail_id"))
    ticket = api("GET", f"/tickets/{ticket_id}")
    st.subheader(f"#{ticket_id} · {ticket['title']}")
    st.text(ticket["description"])
    names = {t["id"]: t["name"] for t in teams}
    st.write(f"Durum: {STATUS[ticket['status']]} · Öncelik: {PRIORITY[ticket['priority']]}")
    st.write(f"Ekip: {names.get(ticket['team_id'], ticket['team_id'])}")
    st.caption(f"Talep sahibi: #{ticket['requester_id']} · Atanan görevli: {ticket['assignee_id'] or 'Atanmadı'}")
    st.caption(f"Oluşturulma: {time_label(ticket['created_at'])}")

    # Düğmeler kullanım kolaylığı sağlar. Asıl yetki kontrolü API'dedir.
    actions = []
    if user["role"] == "agent" and ticket["status"] == "OPEN":
        actions.append(("Talebi üstlen", "claim"))
    if user["role"] == "agent" and ticket["status"] == "IN_PROGRESS" and ticket["assignee_id"] == user["id"]:
        actions.append(("Çözüldü olarak işaretle", "resolve"))
    if ticket["status"] == "RESOLVED" and (user["role"] == "manager" or ticket["requester_id"] == user["id"]):
        actions.append(("Yeniden aç", "reopen"))
    for label, action in actions:
        if st.button(label, key=f"{action}_{ticket_id}"):
            api("POST", f"/tickets/{ticket_id}/{action}")
            success("Talep güncellendi.")

    sla = api("GET", f"/tickets/{ticket_id}/sla")
    with st.container(border=True):
        st.subheader("İlk yanıt hedefi")
        st.write(SLA[sla["status"]])
        st.caption(f"İlk yanıt için son zaman: {time_label(sla['due_at'])} · İlk yanıt: {time_label(sla['first_response_at'])}")
        st.caption("Hedef, ilk uygun görevli yanıtını ölçer; çözüm süresini ölçmez.")

    comments_tab, events_tab = st.tabs(["Yorumlar", "İşlem geçmişi"])
    with comments_tab:
        page = int(st.number_input("Yorum sayfası", min_value=1, step=1, key=f"comments_{ticket_id}"))
        comments = api("GET", f"/tickets/{ticket_id}/comments", params={"limit": 20, "offset": (page - 1) * 20})
        st.caption(f"Toplam {comments['total']} yorum")
        for comment in comments["items"]:
            with st.container(border=True):
                st.caption(f"Kullanıcı #{comment['author_id']} · {time_label(comment['created_at'])}")
                # Kullanıcı metnini HTML/Markdown olarak yorumlamadan göster.
                st.text(comment["body"])
        if ticket["status"] != "RESOLVED":
            with st.form(f"comment_form_{ticket_id}", clear_on_submit=True):
                body = st.text_area("Yeni yorum", max_chars=5000)
                submitted = st.form_submit_button("Yorumu gönder", type="primary")
            if submitted:
                api("POST", f"/tickets/{ticket_id}/comments", json={"body": body})
                success("Yorum kaydedildi.")
        else:
            st.info("Çözülmüş talebe yorum eklemek için talep önce yeniden açılmalı.")
    with events_tab:
        page = int(st.number_input("Geçmiş sayfası", min_value=1, step=1, key=f"events_{ticket_id}"))
        events = api("GET", f"/tickets/{ticket_id}/events", params={"limit": 20, "offset": (page - 1) * 20})
        st.caption(f"Toplam {events['total']} işlem")
        st.dataframe([{"İşlem": EVENTS.get(e["event_type"], e["event_type"]),
                       "Kullanıcı": e["actor_id"], "Zaman": time_label(e["created_at"])}
                      for e in events["items"]], hide_index=True, width="stretch")


# ============================================================================
# 7. YÖNETİCİ İŞLEMLERİ
# ============================================================================
def create_agent():
    st.title("Görevli oluştur")
    st.caption("Oluşturulan görevliyi Ekip yönetimi ekranından ekibe ekle.")
    with st.form("create_agent", clear_on_submit=True):
        fields = account_fields("agent")
        submitted = st.form_submit_button("Görevliyi oluştur", type="primary")
    if submitted:
        user = api("POST", "/users/agents", json=account_payload(fields))
        success(f"Görevli oluşturuldu. Ekibe eklerken kullanacağın kullanıcı numarası: {user['id']}")


def manage_teams(teams):
    st.title("Ekip yönetimi")
    with st.form("create_team", clear_on_submit=True):
        name = st.text_input("Yeni ekip adı", max_chars=100)
        submitted = st.form_submit_button("Ekip oluştur")
    if submitted:
        api("POST", "/teams", json={"name": name})
        success("Ekip oluşturuldu.")
    if not teams:
        return
    options = {t["id"]: t for t in teams}
    selected = st.selectbox("Yönetilecek ekip", options,
                            format_func=lambda x: f"{options[x]['name']} · {'Aktif' if options[x]['is_active'] else 'Pasif'}")
    team = options[selected]
    with st.form(f"team_status_{selected}"):
        active = st.checkbox("Ekip aktif", value=team["is_active"])
        submitted = st.form_submit_button("Aktiflik durumunu kaydet")
    if submitted:
        api("PATCH", f"/teams/{selected}/status", json={"is_active": active})
        success("Ekip durumu güncellendi.")

    members = all_rows(f"/teams/{selected}/members")
    st.subheader("Ekip üyeleri")
    if members:
        st.dataframe([{"No": m["user"]["id"], "Ad": m["user"]["full_name"],
                       "E-posta": m["user"]["email"]} for m in members], hide_index=True, width="stretch")
    else:
        st.info("Ekipte henüz görevli yok.")
    with st.form(f"add_member_{selected}", clear_on_submit=True):
        user_id = int(st.number_input("Eklenecek görevlinin kullanıcı numarası", min_value=1, max_value=2147483647, step=1))
        submitted = st.form_submit_button("Ekibe ekle", disabled=not team["is_active"])
    if submitted:
        api("POST", f"/teams/{selected}/members", json={"user_id": user_id})
        success("Görevli ekibe eklendi.")
    if members:
        users = {m["user"]["id"]: m["user"]["full_name"] for m in members}
        with st.form(f"remove_member_{selected}"):
            target = st.selectbox("Ekipten çıkarılacak görevli", users, format_func=lambda x: f"{users[x]} (#{x})")
            confirmed = st.checkbox("Bu ekip üyeliğini kaldırmak istiyorum.")
            submitted = st.form_submit_button("Üyeliği kaldır")
        if submitted:
            if not confirmed:
                raise ApiError("Üyeliği kaldırmak için onay kutusunu işaretle.")
            api("DELETE", f"/teams/{selected}/members/{target}")
            success("Ekip üyeliği kaldırıldı. Kullanıcı hesabı korunuyor.")


# ============================================================================
# 8. UYGULAMA GİRİŞ NOKTASI
# ============================================================================
def main():
    st.set_page_config(page_title="Servis Takip", layout="wide")
    notice = st.session_state.pop("notice", None)
    if notice:
        st.info(notice)
    try:
        if not st.session_state.get("token"):
            login_page()
            return
        # Her çalıştırmada hesabın güncel rolü ve aktifliği API'den doğrulanır.
        user = api("GET", "/users/me")
        with st.sidebar:
            st.title("Servis Takip")
            st.text(user["full_name"])
            st.caption(f"{ROLES[user['role']]} · Kullanıcı #{user['id']}")
            if st.button("Çıkış yap"):
                clear_session()
                st.rerun()
            st.button("Verileri yenile")
            pages = ["Genel bakış", "Talepler", "Yeni talep", "Talep ayrıntısı"]
            if user["role"] == "manager":
                pages.extend(["Ekip yönetimi", "Görevli oluştur"])
            # Navigasyonu, widget oluşturulmadan önce güncelle.
            if "next_screen" in st.session_state:
                st.session_state["screen"] = st.session_state.pop("next_screen")
            if st.session_state.get("screen") not in pages:
                st.session_state["screen"] = pages[0]
            screen = st.radio("Menü", pages, key="screen")
            st.caption("Tüm saatler Türkiye saatidir. Oturum süresi dolunca yeniden giriş gerekir.")

        if screen == "Genel bakış":
            overview()
        elif screen == "Görevli oluştur":
            create_agent()
        else:
            teams = all_rows("/teams")
            if screen == "Talepler":
                tickets_page(teams)
            elif screen == "Yeni talep":
                new_ticket(teams)
            elif screen == "Talep ayrıntısı":
                ticket_detail(user, teams)
            elif screen == "Ekip yönetimi":
                manage_teams(teams)
    except ApiError as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()
