# Servis Takip Paneli

Mevcut FastAPI uygulamasını HTTP üzerinden kullanan Türkçe Streamlit paneli.
Doğrudan veritabanına bağlanmaz. Yetkilendirme ve iş kuralları API tarafından uygulanır.

## Ekranlar

- Giriş ve requester hesabı oluşturma.
- Yetkiye göre özet, durum/öncelik/SLA sayıları.
- Filtrelenebilir ve sayfalanabilir talep listesi.
- Ekip seçerek yeni talep oluşturma.
- Talep ayrıntısı, sahiplenme, çözme ve yeniden açma.
- Yorum ekleme, yorumları ve işlem geçmişini sayfalama.
- Yönetici için ekip oluşturma, aktiflik, üyelik ekleme/kaldırma.
- Yönetici için agent oluşturma.

## Dosyaların konumu

Bu panel klasörü mevcut servis_takip projesinin ana klasörüne yerleştirilir.
Paketteki .github/workflows/panel.yml aynı projenin .github/workflows klasörüne eklenir.
Mevcut ci.yml dosyası korunur.

## İlk kurulum — proje kökünde PowerShell

API ve veritabanını başlatın:

```powershell
docker compose -f compose.yaml -f compose.api.yaml up -d --wait
```

Panel için ayrı sanal ortam oluşturun:

```powershell
.\.venv\Scripts\python.exe -m venv panel/.venv
.\panel\.venv\Scripts\python.exe -m pip install -r panel/requirements.txt
.\panel\.venv\Scripts\python.exe -m pip check
```

Paneli çalıştırın:

```powershell
.\panel\.venv\Scripts\python.exe -m streamlit run panel/app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats=false
```

Tarayıcı adresi: http://127.0.0.1:8501

API varsayılan adresi http://127.0.0.1:8000 olarak tanımlıdır.
Farklı kurulumlarda panel sürecine SERVIS_API_URL ortam değişkeni verilebilir.
Mevcut yerel kurulumda bu ayarı değiştirmek gerekmez.

Paneli kapatmak için çalıştığı terminalde Ctrl+C kullanın.
Bilgisayar yeniden açıldığında Docker Desktop'ı açın, Compose başlatma komutunu
ve ardından Streamlit çalıştırma komutunu yeniden çalıştırın.
Sanal ortam ve paket kurulumunu her açılışta tekrarlamayın.

## Hesaplar

Mevcut API hesaplarının e-posta ve parolaları geçerlidir.
Panelde kayıt olan hesap requester rolündedir.
İlk yönetici gerekiyorsa mevcut komutu kullanın:

```powershell
docker compose -f compose.yaml -f compose.api.yaml run --rm --no-deps api python -m app.commands.create_manager
```

Yönetici, panelden görevli oluşturduğunda ekranda görevlinin kullanıcı numarası gösterilir.
Ekip yönetimindeki üyelik formuna bu numara yazılır.
Mevcut API'de bütün görevlileri listeleyen bir endpoint bulunmadığı için
üyelik formunda görevli seçimi kullanıcı numarasıyla yapılır.

## Oturum ve veri davranışı

Token yalnızca Streamlit oturum durumunda tutulur; URL'ye veya dosyaya yazılmaz.
Kullanıcı verileri ortak cache içinde tutulmaz. Çıkış, oturum durumunu temizler.
Tarayıcı oturumu yenilendiğinde veya token süresi dolduğunda yeniden giriş gerekebilir.
Panelden çıkış, daha önce üretilmiş tokenı API tarafında iptal etmez;
mevcut API tokenın geçerlilik süresini uygular.

Saatler Europe/Istanbul saat diliminde gösterilir.
Veriler ekran etkileşimlerinde veya Verileri yenile düğmesiyle yeniden okunur;
anlık bildirim veya otomatik arka plan yenilemesi yoktur.

API'nin rol ve iş kuralları nihai yetkilidir. Örneğin ekibinde olmayan bir talebi
üstlenmeye çalışan agent için API'nin hata mesajı panelde gösterilir.
Bağlantı hatasında yazma işlemi otomatik tekrarlanmaz; çift kayıt riskine karşı
önce liste kontrol edilmelidir.

## Testler

Proje kökünde:

```powershell
.\panel\.venv\Scripts\python.exe -m pip install -r panel/requirements-dev.txt
.\panel\.venv\Scripts\python.exe -m pytest panel/tests -q --tb=short
```

Sekiz test Streamlit AppTest kullanır ve HTTP yanıtlarını taklit eder.
Gerçek API/veritabanıyla uçtan uca testin yerini tutmaz.
Mevcut backend testleri ayrı kalır. Panelin kendi GitHub Actions dosyası vardır.

## İlk gerçek kullanım kontrolü

1. Yönetici olarak giriş yapın.
2. Ekip yönetiminden ekip oluşturun.
3. Görevli oluşturun; verilen kullanıcı numarasıyla ekibe ekleyin.
4. Çıkış yapın, requester hesabıyla giriş yapın veya yeni hesap oluşturun.
5. Yeni talep ekranından ilgili ekibe talep gönderin.
6. Agent hesabıyla giriş yapıp talepten Talebi üstlen düğmesini kullanın.
7. Yorum gönderin; SLA ve işlem geçmişini kontrol edin.
8. Çözüldü olarak işaretleyin.

## Kapsam

Bu ek paket yerel panel kullanımını sağlar. Panel henüz Compose servisi değildir;
Windows üzerinde ayrı bir süreç olarak çalışır. API ve PostgreSQL Docker'da kalır.
Mevcut veritabanına migration gerekmez.
