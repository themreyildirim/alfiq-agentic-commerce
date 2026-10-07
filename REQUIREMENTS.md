# A/B gereksinim eşleştirmesi

| Gereksinim | Uygulama / kanıt |
|---|---|
| Normalizasyon, alan/tip doğrulama, kalite, karantina, catalog_version | core.py CatalogManager/build_catalog; reports/data_quality |
| Şema kontrollü politika ve kesin kısıtlar | core.py preflight/quote; tests/test_controls.py |
| search_products/get_product/quote_cart/create_cart_draft/update_cart/request_approval/confirm_cart/cancel_cart | schemas/registry.json, AgentTools; arama <=10, bağlam <=20 |
| Araçla aday bulma, LLM yumuşak seçimi, gerekçe grounding | agent.py, ollama_adapter.py, prompts; ham referans audit'leri |
| En çok iki onarım; ID/fiyat/stok/özellik/yetki doğrulama | core.py grounded_selection/extract_intent; controller unit testleri |
| Çok turlu niyet ve patch; başarısız değişiklikte eski taslağı koruma | M01, M05, M08, M09, M10 |
| SQLite kalıcılık ve yerel backup/restart | StatefulCheckoutStore, M08; drive_backup_saved yerel backup sözleşme adı |
| Açık insan onayı, TTL 900, sürüm bağlı token, idempotency, terminal durum | M01, M02, M04, M06, M07, M11 |
| Bir komutla yama, fiyat/stok drift, zehirli yeni kayıt | scripts/apply_catalog_patch.py, M02/M03/M11/A06, gerçek S3 kalite raporları |
| >=30 vaka / >=8 çok turlu / >=6 saldırı / 5 tekrar | Gerçek 35/12/8 ×5, 365 tur; tam kabul geçti |
| Tur bazlı JSON ve trace, eval tek komut, birim testler | reports, alfiq_b.evaluate CLI, 91 unit/mock testi |
| Orijinal sorgu/senaryo JSON'ları | Gerçek P01-P18, S1/S2/S3/S5/S6: 33 çıktı |
| Kaynaklar, promptlar, şemalar, README, <=2 sayfa tasarım | Bu paket ve DESIGN_NOTE.pdf |
| 3-5 dakika çok turlu + drift demo videosu | Kullanıcı kaydı tamamladığını bildirdi; ayrı video dosyası, içerik burada incelenmedi |
| S4/MCP/mandate/JSON-LD/protokol eşlemesi | Opsiyonel C; uygulanmadı, A/B tesliminin dışında |

Raporlanan %100 bu sabit eval setinin sonucudur. Orijinal girdilerde eksik ülke/varyant güvenli ret veya açıklama üretir; bu sonuçlar başarılı sipariş gibi gösterilmez. S3 ürün adı aramasında leksik kapsam sınırı PUBLIC_OUTPUT_REVIEW.md içinde açıklanır.
