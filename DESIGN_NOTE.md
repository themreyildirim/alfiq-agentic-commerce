# ALFIQ - A/B tasarım notu

## Kararlar ve gerekçeler

LLM niyet ve uygun aday/kanıt seçimi yapar; Decimal fiyat, stok, bütçe ve satıcı politikası kodla doğrulanır. Tüm katalog prompt'a verilmez; tipli araç araması <=10 kayıt, tur bağlamı <=20 ürün. Normalizasyon tek sürümlü SHA-256 katalog üretir. Ürün adı talimatı şüpheli kayıt olarak karantinaya alınır. Eksik özellik kesin bilgiye dönüştürülmez; USD varsayımı açıklanır, EUR dönüşümü yapılmaz. Fiyat aralığı güvenli üst sınıra göre süzülür, checkout net fiyat/varyant gerektirir.

Qwen3 4B Instruct Q4_K_M, GTX 1650 Ti 4 GB / yaklaşık 8 GB RAM için kullanıldı; Gemini kotası sonrasında kullanıcı onayıyla seçildi. Türkçe/İngilizce tipli slotlar, dar insan mesajı bağlam kuralları ve aday/kanıt indeksleri küçük modelin JSON/niyet hatalarını sınırlar. Model gerçek aday ve kanıtı seçer; olgusal metni kod katalogdan çözer, yumuşak amaç yorumunu açıklanmış şablonla ekler. Fiyat/onay token'ı LLM tarafından belirlenmez.

SQLite oturum niyetini, sepeti, olayları ve idempotency sonucunu saklar; yerel backup yeniden başlatmayı destekler. Patch'te atlanan alan korunur; bütçeyi aşan değişiklik pending olur ve eski taslak kalır. Checkout draft/awaiting_approval/needs_reconfirmation/expired/approved/cancelled durumlarıyla yürür. Onay token'ı katalog/politika/sepet sürümü ve 900 saniyelik teklife bağlıdır; güncel insan mesajından açık onay gerekir. Ülke yanıtı eski approval request'i devralamaz.

## Gerçek ölçüm ve sınırlar

v4.8: 35 vaka (12 çok turlu, 8 saldırı), beş tekrar, 365 tur. Doğruluk ve min. durum/seçim tutarlılığı %100; kısıt/grounding ihlali, yetkisiz onay, başarısız kontrol ve store invariant sıfır. Tüm kabul eşikleri karşılandı. 265 gerçek üretim, 454.325 bilinen token; kodla yürüyen 190 tur LLM çağırmadı. Tam tur p50 0,199 s / p95 36,524 s; ücret/elektrik maliyeti ölçülmedi. 91 unit/HTTP mock testi model başarısından ayrıdır.

Orijinal P01-P18 ve beş A/B senaryosu 33 JSON üretir; eksik ülke/varyantla sipariş uydurulmaz. S3 Türkçe bardak sorgusunun İngilizce Glass/Cup isimlerine eşleşmesi sınırlıdır; no_match korunur. Önceki v4.6/v4.7 tam ölçümler sırasıyla 13/10 kontrol hatası verdi; v4.8 güncel-mesaj onay bağlamı kuralıyla son suite geçti. Model/eşik/beklenen sonuçlar değiştirilmedi.

Bu görünür sabit set geliştirmede kullanıldı; kör test ve genel güvenlik garantisi değildir. Sayı/kategori/dil kuralları daha geniş ifadelerde hata yapabilir; öznel gerekçe şablonu sınırlıdır. Windows HTTP timeout üretimi sunucuda iptal etmeyebilir. Katalogda stok adedi/varyant/bakım/kargo verisi yok; gerçek ödeme yapılmaz. C'nin MCP/mandate/JSON-LD kapsamı ve videosu yoktur; A/B videosunun kaydı kullanıcı beyanıyla tamamlandı; video ayrı dosya olarak teslim edilir ve burada incelenmedi.

## Tehdit modeli: saldırı ve karşılık

1. Kullanıcı 'fiyatı 1 USD yap / ADMIN indirim' der: policy/preflight kodda; yetkisiz override reddedilir.
2. Ürün adında 'ignore instructions / confirm_cart': normalizasyonda karantina; katalog metni yetki sayılmaz.
3. Araç çıktısı veya LLM yanlış ID/fiyat/kanıt döndürür: JSON schema + bağımsız catalog/evidence kontrolü; iki onarım sonrası güvenli ret.
4. Sahte/tekrar/eski onay: güncel insan onayı, token sürümü, TTL ve idempotency; onaysız sipariş üretilemez.
5. Fiyat/stok drift'i ile eski teklifi onaylatma: her tur freshness/revalidation, diff ve needs_reconfirmation; yeni token istenir.
6. Model miktar/bütçe/ülke uydurur veya geçmiş onayı taşır: insan mesajı kanıtı, tipli grammar ve niyet kontrolleri; başarısız değişiklik uygulanmaz.

## ALFIQ için ilk üç adım

1. Net varyant/stok adedi, bakım/kargo bilgisi, kanonik ürün türü ve TR/EN eşanlamlılarını içeren sürümlü ürün veri sözleşmesi kurmak.
2. Bağımsız kör test, yeni dil/ifade saldırıları ve üretim izleme ile hata oranı/LLM gecikmesini ayrı ölçmek; katalog büyüdüğünde indeksli aday arama eklemek.
3. İnsan onayı sınırını koruyarak C'yi geliştirmek: kimliği doğrulanmış MCP, süre/kapsam/tutarı sınırlı imzalı mandate ve açık JSON-LD/protokol sözleşmesi; ödeme sistemini ayrı güvenlik incelemesinden sonra bağlamak.
