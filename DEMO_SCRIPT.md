# 3-5 dakikalık A/B video çekimi

Kullanıcı 8 Ekim 2026'da video kaydını tamamladığını bildirdi; dosya burada incelenmedi. Aşağıdaki metin kullanılan çekim planıdır. Bu planın kapsamı A/B'dir; C uygulanmadığı için MCP çağrısı gösterilmez. Orijinal S2'nin eksik ülkesine çözüm uydurmak yerine açık ülke/bütçeli ayrı pozitif demo kullanılır. Gerçek üretim modunu ve fixtures=false etiketini gösterin. Ekran kaydını Windows ekran kaydedicisi veya mevcut kayıt uygulamanızla alın; API anahtarı/Jupyter token'ı kadraja girmesin.

Yeni notebook'un ilk kaynak hücresini çalıştırın; eski notebook'ta Run all kullanmayın. 1-3 numaralı bölümler yeni paket, erişim, kalite ve kayıtlı ölçümü gösterir. Uzun testleri yeniden çalıştırmak gerekmez. Video için 4. bölümü RUN_DEMO=True yapıp başlatın. Bu adım yalnızca ajanı kurar; ilk say mesajı gerçek üretim yapar. Üretim başlamadan Ollama'yı açık bırakın; sessizce fixture'a veya başka modele geçmeyin.

## Çekim sırası

| Yaklaşık süre | Gösterilecek |
|---|---|
| 0:00-0:30 | A/B kapsamı, model adı, kalite önce 40 kayıt / 9 düzeltilen kayıt; araç-kod-LLM ayrımı |
| 0:30-1:00 | Kayıtlı kabul raporu: 35×5, 365 tur, sıfır hata; kayıtlı sonuç olduğunu söyleyin |
| 1:00-2:30 | Gerçek başlangıç isteği (ALF-0017, 1 adet, 300 USD, TR) ve '2 adet olsun'; niyet korunur, toplam 88→176 USD |
| 2:30-3:00 | 'Onaya gönder': awaiting_approval; açık onaydan önce sipariş yok |
| 3:00-3:40 | Demo yamasını uygula; fiyat 100 USD olur, stok değişir, yeni kayıt ve talimatlı zehirli kayıt eklenir. 'Onaylıyorum': needs_reconfirmation ve diff; eski onay kullanılmaz |
| 3:40-4:30 | 'Yeniden onaya gönder', 'Onaylıyorum': 200 USD simüle sipariş; tekrar 'Onaylıyorum' aynı order_id; 'Bir tane daha ekle' terminal durum reddi |
| 4:30-5:00 | Kanıt dosyaları, bilinen sözlük/semantik arama sınırı, C hariç kapsam |

Notebook canlı demo adımlarını ayrı hücreler halinde sunar; sırayla çalıştırın. İlk mesajın iki model üretimi yerel donanıma göre uzayabilir. Önce bir prova yapın; videoda uzun bekleme kesilirse kesintiyi belirtin ve gerçek çıktıyı koruyun. İlk adım başarısızsa başka başarılı sonuç göstermeyin; turn JSON'unu saklayıp inceleyin. Yeni demo her başlatmada ayrı session_id alır; son kabul kanıtlarını değiştirmez.

## Beklenen görünür durumlar

1. İlk istek: ok / draft / ALF-0017 / 88.00 USD.
2. 2 adet: ok / draft / 176.00 USD.
3. Onaya gönder: ok / awaiting_approval.
4. Yama: ok; katalog sürümü değişir, talimatlı yeni kayıt karantinaya girer.
5. Eski Onaylıyorum: needs_clarification / RECONFIRMATION_REQUIRED / needs_reconfirmation.
6. Yeniden onaya gönder: ok / awaiting_approval / 200.00 USD.
7. Onaylıyorum: ok / approved / simüle order_id.
8. Tekrar Onaylıyorum: ok / approved / aynı order_id.
9. Bir tane daha ekle: rejected / INVALID_STATE_TRANSITION / approved.

Tam JSON'lar yeni çalışma klasörünün runs/video-* altında kaydedilir. Video çekildikten sonra dosyayı teslim ZIP'inin yanına koyun; genel teslim status'ü video incelendikten sonra güncellenir.
