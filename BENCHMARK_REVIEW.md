# Gerçek v4.8 kabul ölçümü

35 vaka × 5 tekrar = 175 bağımsız vaka çalışması, 365 tur. 12 çok turlu ve 8 saldırı vakası. Çıktı şeması, sepet durumu, istek-niyet eşleşmesi, katalog iddiaları ve store invariant kontrolleri geçmiştir. Model aynı Qwen3 4B Q4_K_M; bağlam 4096, en fazla 1024 çıktı token, taşıma sınırı 120 saniye, temperature 0 / seed 42. Örneklem sabit, görünür ve geliştirme sırasında kullanılmıştır; kör test değildir.

| Ölçüt | Sonuç | Kabul eşiği |
|---|---:|---:|
| Durum doğruluğu | %100 | En az %90 |
| Hard constraint ihlali | 0 | 0 |
| Grounding hatası | 0 | 0 |
| Yetkisiz onay | 0 | 0 |
| Minimum durum tutarlılığı | %100 | %100 |
| Minimum seçim tutarlılığı | %100 | En az %80 |
| Başarısız ayrıntılı kontrol / store invariant | 0 / 0 | 0 / 0 |

Tüm eşikler geçti, complete ve live_acceptance_passed true. 405 araç çağrısı, 265 gerçek LLM üretimi ve 454.325 bilinen token. 190 tur model çağırmadığı için token toplamı null; bilinmeyen kullanım tahmin edilmedi. p50 0,199 saniye, p95 36,524 saniye tam tur gecikmesidir. Kısa kod adımları medyanı düşürür; model üretiminin medyanı olarak yorumlanamaz. Ücret/elektrik maliyeti ölçülmedi (null).

91 birim/HTTP mock testi ayrı olarak geçti. Üç kontrol-only bozuk model yanıtı A02/A03/A08 canlı suite'e eklenmedi; fixture/controller testlerinde tutulur. Canlı sonuca mock başarı eklenmedi. Üç vakalık hedefli 50 tur başarı kanıtı tam suite'in yerine kullanılmadı.

## Geliştirme sırasında görülen ve saklanan hatalar

- v4.5 tek tekrar: %78,08 doğruluk, 20 kontrol hatası; modelin desteklenmeyen niyet alanları ve yanlış çıkarımları. Tipli slotlar ve genel insan mesajı kuralları geliştirildi.
- v4.6 tam tekrar: %98,90 doğruluk, 13 kontrol hatası. Spa kategori sorgusunun ürün adı filtresine dönüşmesi ve onay eylemi hatası düzeltildi.
- v4.7 tam tekrar: %98,63 doğruluk, 10 kontrol hatası. Gönderim ülkesi yanıtı eski onaya gönder eylemini taşıdığı için sepet erken awaiting_approval oldu. v4.8 güncel insan mesajında onay bağlamı yoksa bu eylemi wire şemasından dışlar.
- v4.8 tam tekrar: 365/365 durum ve tüm kontrol başarıları. Model, eşikler ve beklenen benchmark sonuçları değiştirilmedi.

İyileştirme tek başına model kalitesini ölçmez; sonuç model, prompt, grammar, araç ve kod kontrollerinin toplamıdır. Küçük Türkçe/İngilizce sözlük ve dar ifade kuralları genelleme sınırıdır. Yeni kör eval ve daha büyük katalog üzerinde ölçüm ilk geliştirme hedefidir. Eski ham başarısız raporlar bu ZIP'e karıştırılmadı; geliştirme çalışma alanında korunur.
