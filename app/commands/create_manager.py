# ============================================================
# İÇE AKTARMALAR
# ============================================================

from getpass import getpass

from psycopg.errors import UniqueViolation
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import engine
from app.models import User, UserRole
from app.schemas.user import UserCreate
from app.security import hash_password


# ============================================================
# YÖNETİCİ OLUŞTURMA
# ============================================================

def main() -> int:
    """
    Terminalden alınan bilgilerle yeni bir yönetici oluşturur.

    Mevcut bir hesabın rolünü veya parolasını değiştirmez.
    Başarıda 0, beklenen giriş hatalarında 1 döndürür.
    """

    # --------------------------------------------------------
    # 1. Bilgileri kullanıcıdan al
    # --------------------------------------------------------

    print("Yeni yönetici hesabı oluşturulacak.")

    full_name = input("Ad soyad: ")
    email = input("E-posta: ")

    # Parola komut satırı argümanı olarak verilmez.
    # Normal terminalde yazılan karakterler ekranda gösterilmez.
    password = getpass("Parola: ")
    password_confirmation = getpass("Parolayı tekrar yazın: ")

    if password != password_confirmation:
        print("Parolalar eşleşmiyor. Hesap oluşturulmadı.")
        return 1

    # --------------------------------------------------------
    # 2. API kaydında kullandığımız kurallarla doğrula
    # --------------------------------------------------------

    try:
        payload = UserCreate(
            full_name=full_name,
            email=email,
            password=password,
        )
    except ValidationError as exc:
        print("Bilgiler doğrulanamadı:")

        # Hatanın giriş verisini yazdırmayız; parola içerebilir.
        for error in exc.errors(include_input=False, include_context=False):
            field = ".".join(str(part) for part in error["loc"])
            print(f"- {field}: {error['msg']}")

        return 1

    # --------------------------------------------------------
    # 3. Yeni yönetici kaydını oluştur
    # --------------------------------------------------------

    with Session(engine) as session:
        existing_user_id = session.scalar(
            select(User.id).where(User.email == str(payload.email))
        )

        if existing_user_id is not None:
            print("Bu e-posta zaten kayıtlı. Mevcut hesap değiştirilmedi.")
            return 1

        user = User(
            full_name=payload.full_name,
            email=str(payload.email),
            password_hash=hash_password(
                payload.password.get_secret_value()
            ),
            role=UserRole.MANAGER,
        )

        session.add(user)

        try:
            # Kimliği commit öncesinde alırız.
            session.flush()
            user_id = user.id
            session.commit()

        except IntegrityError as exc:
            session.rollback()

            # Ön kontrolden sonra başka bir işlem aynı e-postayı
            # kaydetmişse veritabanındaki benzersizlik kuralı korur.
            if (
                isinstance(exc.orig, UniqueViolation)
                and exc.orig.diag.constraint_name == "uq_users_email"
            ):
                print("Bu e-posta zaten kayıtlı. Hesap oluşturulmadı.")
                return 1

            # Beklemediğimiz veritabanı hatalarını gizlemeyiz.
            raise

    print(f"Yönetici oluşturuldu. Kullanıcı kimliği: {user_id}")
    return 0


# ============================================================
# KOMUT SATIRI GİRİŞ NOKTASI
# ============================================================

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        engine.dispose()