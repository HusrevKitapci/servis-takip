# ============================================================================
# 1. PYTHON ÇALIŞMA ORTAMI
# ============================================================================

# Projemizdeki Python 3.12 ailesini kullanıyoruz.
# slim-bookworm, Debian tabanlı ve daha küçük bir Python imajıdır.
FROM python:3.12-slim-bookworm


# ============================================================================
# 2. PYTHON DAVRANIŞI VE ÇALIŞMA KLASÖRÜ
# ============================================================================

# Konteyner içinde .pyc dosyaları oluşturma.
# Logları tamponda bekletmeden terminale gönder.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Bundan sonraki göreli dosya yolları /app klasörüne göre değerlendirilir.
WORKDIR /app


# ============================================================================
# 3. POSTGRESQL İSTEMCİ KÜTÜPHANESİ
# ============================================================================

# psycopg'nin saf Python sürümü sistemde libpq bulunmasını gerektirir.
# libpq5, PostgreSQL sunucusu değildir; bağlantı için istemci kütüphanesidir.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*


# ============================================================================
# 4. PYTHON BAĞIMLILIKLARI
# ============================================================================

# Önce yalnızca bağımlılık listesini kopyalıyoruz.
# Uygulama kodu değiştiğinde, bu dosya aynı kaldıysa Docker bu katmanı
# önbellekten kullanabilir ve paketleri tekrar indirmeyebilir.
COPY requirements.txt ./

RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check


# ============================================================================
# 5. UYGULAMA DOSYALARI
# ============================================================================

# Yalnızca uygulamanın çalışması ve migration için gereken dosyaları al.
# .env dosyası imaja kopyalanmaz; ayarlar çalıştırma sırasında sağlanır.
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY logging.json ./


# ============================================================================
# 6. UYGULAMAYI ÇALIŞTIRACAK KULLANICI
# ============================================================================

# Uygulama root yerine ayrı bir kullanıcıyla çalışır.
# Kaynak dosyalarını okuyabilir; çalışma sırasında kodu değiştirmesi gerekmez.
RUN groupadd --system appuser \
    && useradd --system --gid appuser --no-create-home appuser

USER appuser


# ============================================================================
# 7. API BAŞLATMA KOMUTU
# ============================================================================

# EXPOSE, kullanılan portu belgeler; bilgisayara port açma işlemini
# Compose dosyasındaki ports ayarı yapar.
EXPOSE 8000

# 0.0.0.0: Konteynerin ağ arayüzlerinden gelen bağlantıları kabul et.
# --reload kullanmıyoruz; bu imajın içindeki kod sabittir.
# Log ayarları önceki aşamada oluşturduğumuz logging.json dosyasından okunur.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-config", "logging.json", "--no-access-log"]