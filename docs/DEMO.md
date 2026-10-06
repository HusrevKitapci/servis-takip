# Servis Takip — Demo Rehberi

Bu rehber, çalışan uygulamanın temel iş kurallarını Swagger UI üzerinden
göstermek için hazırlanmıştır.

API adresi: http://127.0.0.1:8000/docs

## 1. Hazırlık

- API ve PostgreSQL çalışıyor olmalı.
- Migration dosyaları uygulanmış olmalı.
- Giriş bilgileri bilinen bir manager hesabı bulunmalı.
- Yeni demo hesaplarında kullanılacak parolalar 15–128 karakter olmalı.

Yeni manager gerekiyorsa:

```powershell
docker compose -f compose.yaml -f compose.api.yaml run --rm --no-deps api python -m app.commands.create_manager
```

Mevcut yönetici hesabı kullanılabiliyorsa yeniden oluşturmak gerekmez.

Demo sırasında oluşturulan kayıtlar geliştirme veritabanında kalır.
Gerçek kişilere ait bilgi kullanmayın.

## 2. Giriş yapma

Swagger UI'da Authorize düğmesine basın.

- username: Hesabın e-posta adresi.
- password: Hesabın parolası.

Rol değiştirmek için Authorize penceresinde önce Logout,
ardından diğer hesabın bilgileriyle giriş yapın.

Her değişimden sonra GET /users/me çağrısıyla aktif hesabı doğrulayın.

## 3. Yönetici olarak ekip hazırlama

Manager hesabıyla giriş yapın.

### 3.1. Ekip oluşturun

POST /teams:

```json
{
  "name": "Demo Teknik Destek"
}
```

Yanıttaki id değerini not edin. Sonraki işlemlerde bu değer team_id olacak.

Aynı isim daha önce kullanılmışsa yeni bir isim seçin.

### 3.2. Görevli oluşturun

POST /users/agents:

```json
{
  "full_name": "Demo Servis Görevlisi",
  "email": "demo.agent@example.com",
  "password": "Yalnizca-Demo-Icin-4827!"
}
```

Bu örnek parola yalnızca yerel demo hesabı içindir.

Yanıttaki id değerini not edin. Bu değer agent kullanıcısının user_id değeridir.
Yanıttaki role alanı agent olmalıdır.

E-posta daha önce kullanılmışsa mevcut hesabı kullanın veya yeni e-posta seçin.

### 3.3. Görevliyi ekibe ekleyin

POST /teams/{team_id}/members:

- URL'deki team_id: Az önce oluşturulan ekibin kimliği.
- Gövdedeki user_id: Az önce oluşturulan agent hesabının kimliği.

Swagger'ın örnek JSON gövdesindeki user_id değerini gerçek kimlikle değiştirin.

Kimliklerin 1 veya 2 olduğunu varsaymayın; API yanıtındaki değerleri kullanın.

## 4. Talep sahibi hesabı oluşturma

POST /users:

```json
{
  "full_name": "Demo Talep Sahibi",
  "email": "demo.requester@example.com",
  "password": "Yalnizca-Demo-Icin-7359!"
}
```

Yanıttaki role alanı requester olmalıdır.

Kayıt isteğine role eklemeyin.
Normal kayıt endpoint'i istemcinin rol seçmesine izin vermez.

## 5. Requester olarak talep oluşturma

Manager oturumundan çıkın.
Requester hesabıyla giriş yapın.

GET /users/me ile hesabı kontrol edin.

POST /tickets isteğinde şu alanları kullanın:

| Alan | Değer |
|---|---|
| title | Demo bilgisayarda ağ bağlantısı sorunu |
| description | Bilgisayar ağa bağlanıyor ancak şirket içi uygulamaya erişemiyor. |
| priority | HIGH |
| team_id | Oluşturduğunuz ekibin gerçek kimliği |

Yanıttaki talep id değerini not edin.

Beklenen başlangıç durumu: OPEN.

GET /tickets/{ticket_id}/sla ile SLA durumunu inceleyin.

Yeni oluşturulan HIGH öncelikli talep için:

- Hedef süre 3600 saniyedir.
- Henüz uygun görevli yanıtı yoksa ve bir saat geçmediyse durum WAITING olur.

## 6. Agent olarak talebi sahiplenme

Requester oturumundan çıkın.
Agent hesabıyla giriş yapın.

GET /users/me ile hesabı doğrulayın.

POST /tickets/{ticket_id}/claim çağrısını yapın.

Beklenen:

- Talep IN_PROGRESS durumuna geçer.
- assignee_id, giriş yapan agent hesabının kimliği olur.

SLA'yı tekrar okuyun.
Sahiplenmek tek başına ilk yanıt sayılmaz; yorum yoksa SLA henüz karşılanmış olmaz.

## 7. İlk yanıtı verme

Agent hesabıyla POST /tickets/{ticket_id}/comments:

```json
{
  "body": "Talebinizi aldım. Ağ bağlantısı ve uygulama erişimini kontrol ediyorum."
}
```

Ardından GET /tickets/{ticket_id}/sla çağrısını yapın.

Oluşturmadan bu yana hedef süre aşılmadıysa durum MET olmalıdır.
Hedef süre geçtikten sonra ilk yanıt verildiyse MISSED olur.

GET /tickets/{ticket_id}/events ile geçmişi inceleyin.

Talep oluşturma, sahiplenme ve yorum ekleme olaylarını görebilirsiniz.

## 8. Talebi çözme

Atanmış agent hesabıyla:

POST /tickets/{ticket_id}/resolve

Beklenen:

- Durum RESOLVED olur.
- Çözüm zamanı kaydedilir.
- Olay geçmişine çözüm olayı eklenir.

## 9. Talebi yeniden açma

Requester hesabına geri dönün.

POST /tickets/{ticket_id}/reopen

Beklenen:

- Durum OPEN olur.
- Önceki atama ve çözüm zamanı temizlenir.
- Yeniden açılma olayı kaydedilir.
- İlk yanıt SLA sonucu yeniden başlatılmaz.

## 10. Görünürlük sınırını gösterme

Farklı bir requester hesabı oluşturup onunla giriş yapın.

Bu hesap, ilk requester'a ait demo talebini:

- Kendi talep listesinde görmemeli.
- Kimliğini bilse bile ayrıntı endpoint'inden okuyamamalı.

Görünürlük dışındaki talep için 404 yanıtı beklenir.

Bu örnek, talep kimliğini bilmenin erişim yetkisi vermediğini gösterir.

## 11. Raporu gösterme

GET /reports/tickets/summary çağrısını farklı rollerle deneyin.

Raporun kapsamı giriş yapan kullanıcının görebildiği taleplerdir.
Veritabanında daha önce oluşturulmuş kayıtlar varsa toplamlar yalnızca
bu demoda oluşturduğunuz kayıtlardan oluşmayabilir.

## 12. İstek kimliğini gösterme

Herhangi bir API isteğinin Response headers bölümünde X-Request-ID değerini bulun.

Terminalde:

```powershell
docker compose -f compose.yaml -f compose.api.yaml logs --tail 100 api
```

Aynı request_id değerini taşıyan log kaydını bulun.

Bu eşleştirme, bir istemci isteğini sunucudaki kayıtla ilişkilendirmeyi gösterir.

## 13. Sunum sırasında açıklanabilecek teknik kararlar

- Kullanıcı rolünü normal kayıt isteğinden neden almıyoruz?
- Görünürlük filtresini neden ortak sorguda tutuyoruz?
- Sahiplenmede yalnızca önce okuyup sonra güncellemek neden yeterli değil?
- İşlem ile olay kaydı neden aynı transaction içinde?
- Sahiplenmek neden ilk yanıt sayılmıyor?
- Eski SLA politikasını neden olay kaydında saklıyoruz?
- Test veritabanını neden geliştirme veritabanından ayırıyoruz?
- CI, yerel testlere ek olarak neyi kontrol ediyor?

Demo sırasında gösterilmeyen eşzamanlılık davranışı,
otomatik testlerde ayrı bağlantılar kullanılarak kontrol edilir.