# ALFIQ Agentic Commerce - A + B

## Teslim durumu

Kaynak ve ölçüm paketi v4.8'dir. Kullanıcının Windows bilgisayarında **gerçek yerel Ollama modeliyle** 35 vaka × 5 tekrar / 365 tur tamamlandı: tüm kabul eşikleri geçti, başarısız kontrol sıfır. Orijinal 18 sorgu ve S1/S2/S3/S5/S6 için 33 ayrı JSON çıktı da gerçek modelle kaydedildi. 91 birim/HTTP mock testi ayrı kanıttır. Kullanıcı video kaydını tamamladığını bildirdi. Video dosyası ZIP'in yanında ayrıca teslim edilir; içeriği paket hazırlığında incelenmedi. `DEMO_SCRIPT.md` kayıt akışını, `SUBMISSION_STATUS.json` kaynak/kanıt hazırlığı ile video incelemesinin ayrı durumlarını gösterir.

Kapsam zorunlu A ve B'dir. S4, MCP, imzalı mandate, JSON-LD ve protokol eşlemesi isteğe bağlı C kapsamındadır ve uygulanmamıştır. Video A/B'nin çok turlu işlem ve drift davranışını gösterir; MCP çağrısı gösterildiği iddia edilmez.

## Mimari

`alfiq_b` modülü A ve B'yi birlikte uygular. `core.py`: normalizasyon, SHA-256 katalog sürümü, politika doğrulaması, Decimal fiyatlama, aday kombinasyonları, grounding, tipli araçlar, SQLite sepet/durum makinesi. `agent.py`: konuşma niyeti, patch birleşimi, yeniden doğrulama, onay akışı ve agent-turn.v2 JSON. `ollama_intent_slots.py` / `ollama_grounding_hints.py`: küçük model için tipli çıkarım ve güncel insan mesajına bağlı kurallar. `ollama_adapter.py`: aday ve katalog kanıtı indekslerini doğrulanmış çıktıya çevirir. `evaluate.py`: sürüm kilitli, devam edilebilir eval.

LLM'ye tüm katalog gönderilmez: araç çıktısı en fazla 10 kayıt, tur bağlamı en fazla 20 benzersiz ürün. Model aday ve kanıt seçer; fiyat, stok, bütçe, indirim ve yetki kodda uygulanır. Gerekçedeki olgular seçilen katalog referansından, amaç yorumu açıklanmış şablondan gelir; bu serbest metin üretimi gibi sunulmaz. Dar Türkçe/İngilizce sayı, kategori, bütçe, eylem kuralları modelin yapısal hatalarını sınırlar ve audit kaydı bırakır. Yeni ifadeler üzerinde genelleme ayrıca ölçülmelidir.

## Kurulum: Colab yerel çalışma zamanı veya Jupyter

1. Bu klasörü açın. Ollama açık olsun; kurulu model `qwen3:4b-instruct-2507-q4_K_M`. Model dosyası ZIP'e dahil değildir. Kuruluysa yeniden indirmeyin; ilk kurulum için `ollama pull qwen3:4b-instruct-2507-q4_K_M`.
2. Klasörde PowerShell açıp çalıştırın:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install notebook -r requirements.txt
.\.venv\Scripts\python.exe -m notebook --ServerApp.ip=127.0.0.1 --ServerApp.port=8888 --ServerApp.port_retries=0 --ServerApp.allow_origin=https://colab.research.google.com --ServerApp.allow_credentials=True --no-browser
```

3. `ALFIQ_A_B_v4_8_Local.ipynb` dosyasını Colab'da açıp **Connect → Connect to local runtime** seçin. PowerShell'de çıkan token'lı Jupyter URL'sini kullanın; token'ı videoda göstermeyin. Yerel Jupyter arayüzü de kullanılabilir.
4. Notebook kaynakları ve son kanıtları gömülü ZIP olarak taşır; uzun base64 hücresi bu arşivdir. Ek ZIP/JSON yüklemek gerekmez. Bulut Colab bilgisayarınızdaki localhost Ollama'ya ulaşamaz. API anahtarı veya Colab GPU gerekmez.
5. Yeni notebook `ALFIQ_work_v4_8` klasörüne kurulur; eski çalışma kaynaklarını ve kanıtlarını değiştirmez. Kanıtları okumak model çağrısı yapmaz. Canlı demo/eval hücreleri varsayılan kapalıdır.

## Kullanım

```python
from alfiq_b.agent import make_agent, TURN_SCHEMA
agent = make_agent('runs/example', mode='live', provider='ollama',
                   llm_options={'num_ctx':4096, 'timeout':120})
result = agent.run_turn('session-1',
    "ALF-0039 ürününden 1 adet, 150 USD bütçe, TR gönderim; hediyelik.")
```

`run_turn` gerçek üretim yapabilir. `mode='offline_fixture'` hazır model yanıtları kullanır; gerçek LLM kalite kanıtı değildir. Ollama'nın internetsiz gerçek üretimi `live` olarak kaydedilir. SQLite ve yerel backup oturumu korur. JSON'daki `drive_backup_saved` alanı eski sözleşme adıdır; bu yerel sürümde backup diskteki kopyadır, Google Drive bağlantısı değildir.

## Tek komutla test ve eval

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m alfiq_b.evaluate --mode offline_fixture --repetitions 5 --output runs/fixture-check
.\.venv\Scripts\python.exe -m alfiq_b.evaluate --mode live --provider ollama --allow-live --repetitions 5 --output runs/new-live-eval
.\.venv\Scripts\python.exe -m alfiq_b.public_runner --mode live --provider ollama --allow-live --output runs/new-public
```

Mevcut çıktı dizininden devam etmek için `--resume` ekleyin. Farklı model/ayar/suite sonuçları birleştirilmez. Notebook eval hücresi ayrıca kaynak özetini kilitler. Yeni canlı ölçüm eski teslim kanıtlarını değiştirmez. 38 fixture vaka (385 tur) içinde üç ek kontrollü bozuk model çıktısı vardır; canlı suite bunları dışarıda bırakır ve 35 vakadır. Hazır fixture çıktıları model başarısı olarak raporlanmaz.

## Tek komutla yama

```powershell
.\.venv\Scripts\python.exe scripts/apply_catalog_patch.py --state-root runs/example --patch examples/drift_patch.json
```

Yama bir ürün listesidir; aynı ID güncellenir, yeni ID eklenir. Başarısız yama aktif kataloğu değiştirmez. İlgili ajanı aynı state-root ile yeniden açın; sonraki tur yeni katalog sürümünü görür. Yama komutu kalite öncesi/sonrası ve sonucu aynı state-root altında kaydeder. Aktif demo ajanında notebook `demo.patch()` aynı işlemi uygular.

## Kanıtları nerede bulurum?

| Dosya | Anlamı |
|---|---|
| `reports/live_v4_8_acceptance_passed/metrics.json` | 35 vaka, 12 çok turlu, 8 saldırı, beş tekrar; tam kabul |
| `.../results.jsonl` ve `store_checks.jsonl` | 365 turun JSON'ları, kontrol ve kalıcı durum bütünlüğü |
| `.../ollama_intent_refs.jsonl`, `.../ollama_selection_refs.jsonl` | 175 gerçek niyet ve 90 gerçek seçim çağrısının ham referansları |
| `.../source_lock.json`, `source_snapshot/` | Ölçülen kod/girdi/şema SHA-256 özetleri ve kaynak kopyası |
| `reports/live_v4_8_public/cases/` | Orijinal 18 sorgu ve beş A/B senaryosunun 33 tur bazlı çıktısı |
| `reports/data_quality/` | Gerçek S3 yamasından önce/sonra kalite ve uygulanan yama |
| `reports/offline_v4_8/unit_tests.txt` | 91 birim ve mock testinin kaydı |
| `BENCHMARK_REVIEW.md`, `PUBLIC_OUTPUT_REVIEW.md` | Sonuçların yorumu ve sınırlamaları |
| `DESIGN_NOTE.pdf` | İki sayfalık kararlar, tehdit modeli, ölçüm ve sonraki üç adım |

Ölçüm: doğruluk ve min. durum/seçim tutarlılığı %100; kısıt/grounding ihlali sıfır; yetkisiz onay sıfır. p50 199,488 ms, p95 36.523,667 ms **tam tur** süresidir; kodla yürüyen 190 tur ile LLM kullanan 175 tur aynı dağılımdadır. 265 üretim, 454.325 bilinen token; LLM çağrısı olmayan 190 turun token alanı null kalmıştır. API/electricity USD maliyeti ölçülmedi. Bu sabit katalog ve test kümesindeki başarı farklı dillere, kataloglara veya serbest ifadelere garanti değildir.

## Paket doğrulama ve son adım

`py -3.11 scripts/verify_manifest.py` dosya özetlerini denetler. `manifest.json` notebook, kaynaklar ve raporları kapsar; kendisini veya sonradan çekilen videoyu kapsamaz. Kaynak testten sonra değiştirilmemiştir. Eski başarısız geliştirme kayıtları çalışma alanında korunur; kısa geçmiş `BENCHMARK_REVIEW.md` içindedir.

Teslim: bu ZIP ve kullanıcı tarafından kaydedilen 3-5 dakikalık A/B videosu. Video çok turlu akış, drift ve yeniden onayı göstermelidir. Video kaydı kullanıcı beyanıyla tamamlandı; dosya burada incelenmedi. Opsiyonel C kapsamı dışarıdadır.
