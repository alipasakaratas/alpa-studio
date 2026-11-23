# Alpa Studio

[English](README.md) · **Türkçe**

Alpa Studio, Unity iOS/Android oyun geliştirmek için yerelde çalışan, sürümlenmiş bir Claude Code çerçevesidir. Her oyuna kendine ait bir `.claude/` stüdyosu ve `docs/studio/` yönetişim katmanı kurar. Bunu yaparken genel Claude, Unity, Xcode, Android, Blender, kabuk veya kimlik bilgisi ayarlarına dokunmaz.

Sürüm: **0.4.0 MVP** · Lisans: Apache-2.0 · Çalışma bağımlılıkları: Python 3.9+, Git, Claude Code. Unity yalnızca Unity işlerini çalıştırmak için gerekir.

## Gerçek projelerden kanıtlar

Ölçümler beş gerçek projenin Claude Code dökümlerinden alındı. Bunların ikisi bu şablonla kurulan Unity oyunları, biri de stüdyonun çıkarıldığı satranç projesi. Sayılar, stüdyonun oturum politikasından önceki dönemle sonraki dönemi karşılaştırır.

| | Önce | Sonra |
|---|---:|---:|
| API turu başına token | 221K | **70K (−%68)** |
| Herhangi bir oturumdaki en yüksek bağlam | 965K | **130K** |
| Biten görev başına token (satranç projesi) | 61M | **21M (−%66)** |
| Commit başına token (blok bulmaca projesi) | 7.9M | **3.6M (−%54)** |
| Commit başına token (stüdyosuz kontrol projesi) | 2.6M | 2.6M |
| Aktif gün başına toplam token | 431M | 517M (**+%20**, daha fazla iş yapıldı) |

Tüm sayılar, işe yaramayan şeyler, yöntem ve ölçümü kendi makinenizde yeniden üreten script [docs/EVIDENCE.md](docs/EVIDENCE.md) dosyasında (İngilizce). Script'i `python3 tools/usage_scan.py --split <tarih>` ile çalıştırabilirsiniz.

## Şu an çalışanlar

- **Güvenli kurulum:**
  - Unity, Git ve yazma izni ön kontrolü zorunlu; kurulum varsayılan olarak deneme (dry-run) modunda çalışır.
  - Çakışan dosyaları atlar, mevcut ayarları koruyarak birleştirir.
  - Yedek alır, sağlama toplamı tutar, durumu proje içinde saklar.
- **Tamamen proje içi çalışma:** kurulan oyunlar çerçevenin kaynak deposuna bağlı değildir.
- **Proje kapsamlı bileşenler:**
  - 46 Claude alt ajanı ve isteğe bağlı çalışan yedi skill.
  - Deterministik hook'lar ve en aza indirilmiş sabit bağlam.
  - Araçların tamamıyla otonom çalışma; proje güvenlik hook'ları ve görev dalları bunu sınırlar.
- **Açık, role dayalı model politikası:**
  - Opus: yönetim, mimari, tüm yaratıcı/tasarım rolleri ve tüm üretim kodu rolleri.
  - Sonnet: `gameplay-qa` (test kodunu yazar ve çalıştırır), araştırma ve kalan QA rolleri.
  - Haiku: süreklilik ve kaynak rolleri.
- **Yönetim ve iş akışı:**
  - Studio Director yönlendirmesi ve sahip onay kuyruğu.
  - Değiştirilemez karar kilitleri; ücretli servis ve yayın kapıları.
  - Kaynak kanıt defteri ve kalıcı görev kuyruğu.
  - Her görev için yeni bir Claude oturumu açan runner; işler incelenebilir görev dallarında yapılır.
- **Gerçeği söyleyen sağlık kontrolleri:** Claude, Unity, Git, Python, Blender, ffmpeg, Android AVD/cihaz durumu, iOS Simulator runtime/cihaz durumu, donanım, bellek ve depolama.
- **Yalnızca localhost'ta çalışan Mission Control:** onay işlemleri, görev/QA durumu, varlık galerisi ve yetenek durumu.
- **Görsel QA:** altı eksenli ağırlıklı puanlama, iç hedef 95/100. Sertifika için bağımsız bir gözden geçirenin kimliği zorunlu.
- **Diğer güvenceler:**
  - Yıkıcı olmayan Git kontrol noktası defteri.
  - Veriyle tanımlanan sertifika profilleri (`profiles/example.json` veya kendi JSON dosyanız).
  - Açık çocuk, gizlilik, güvenlik ve haklar kapıları.
- **Çekirdek yalnızca Python standart kütüphanesiyle yazılmıştır:** paket indirmez, ücretli bir çalışma zamanı servisi kullanmaz.

## Dürüst MVP sınırı

Ayrıntılar için [Uygulama durumu](docs/IMPLEMENTATION-STATUS.md) belgesine bakın. Aşağıdakiler **planlandı ama henüz uygulanmadı**:

- görsel ve 3D üretim sağlayıcıları;
- Blender çalıştırma hatları;
- görev başına tam worktree izolasyonu;
- yıkıcı geri alma;
- gerçek derleme ve cihaz çalıştırma;
- mağazaya gönderim;
- barındırılan, çok kullanıcılı Mission Control;
- otomatik hukuki sonuç çıkarma.

Çerçeve bu yetenekleri algılar ve kapıların arkasında tutar; onları çalıştırmış gibi davranmaz.

## Güvenli kurulum

İlk komut her zaman yalnızca okunan bir plandır:

```sh
./install.sh --project /absolute/path/to/UnityProject --profile example
```

JSON çıktısındaki işlemleri gözden geçirin. Ön kontrol ve çakışma listesi kabul edilebilirse uygulayın:

```sh
./install.sh --project /absolute/path/to/UnityProject --profile example --apply
```

`example`, çerçeveyle gelen nötr bir profildir. Kendi oyununuz için `profiles/example.json` dosyasını kopyalayıp düzenleyin. Sonra ya yolunu verin (`--profile path/to/my-game.json`) ya da dosyayı `profiles/<id>.json` olarak ekleyin; doğrulanan her profil, Python kodu değiştirmeden kabul edilir.

Kurulumun mevcut dosyalara davranışı:

- Kullanıcı düzeyindeki `~/.claude` dosyalarını asla değiştirmez.
- Projenin mevcut `.claude/settings.json` değerleri korunur; çerçevenin hook'ları ve yasak kuralları bunlarla birleştirilir.
- Tanınmayan mevcut dosyaların üzerine yazmaz; onları atlar ve raporlar.

## Günlük komutlar

```sh
# Makinenin ve projenin gerçek durumu
./bin/alpa doctor --project /path/to/game

# Kritik bir kararı kuyruğa ekle
./bin/alpa approval create --project /path/to/game \
  --title "Choose the approved art concept" --category design-authority

# İş ekle; gerekiyorsa --requires-approval APR-... ekle
./bin/alpa task add --project /path/to/game --title "Research competitors" \
  --prompt "Run source-backed competitor, video, and review research."

# Sıradaki yeni Claude oturumunu çalıştırmadan göster; bilinçli olarak --execute ekle
./bin/alpa runner --project /path/to/game

# Yerel Mission Control
./bin/alpa dashboard --project /path/to/game

# Dürüst sertifika raporu (her kapının kanıtı olana kadar sıfır dışı kodla çıkar)
./bin/alpa certify --project /path/to/game
```

## Günlük kullanım: otomatik mod (varsayılan)

```sh
scripts/studio-start.sh     # veya: scripts/alpa run  -- her görev için yeni bir Claude oturumu
scripts/alpa status          # runner, aktif görev, onaylar, bağımlılıklar
scripts/alpa pause           # mevcut görevden sonra dur
scripts/alpa resume
```

Elle çalıştırma yedeği:

1. `claude`'u etkileşimli başlatın.
2. `/clear` çalıştırın.
3. Bir devam ifadesi yazın (varsayılan: `start` veya `continue`).

`/clear` tek başına hiçbir şey çalıştırmaz. Devam ifadeleri `.alpa-studio/config.json` içinde `execution.continue_phrases` altında ayarlanır, örneğin `["start", "continue", "devam"]`. Ayrıntılar: [docs/CONTEXT-SESSION-MANAGEMENT.md](docs/CONTEXT-SESSION-MANAGEMENT.md).

Kurulu bir projeyi `alpa upgrade` ile güncelleyin ([docs/MIGRATION.md](docs/MIGRATION.md)).

## Mevcut projeyi taşıma

Taşıma yalnızca eski Claude kontrol katmanını değiştirir. Taşıma sırasında:

- geri yüklenebilir bir yedek alınır ve Alpa Studio kurulur;
- projeye özgü ajanlar ve kurallar eklenti olarak geri yüklenir;
- oyun kodu, varlıklar ve belgeler korunur;
- mevcut Unity çalışma zamanı paketleri, bilinçli bir paket taşımasına kadar yerinde kalır.

```sh
# Yalnızca gözden geçir
./bin/alpa migrate --project /path/to/game --profile example

# Gözden geçirdikten sonra açıkça değiştir
./bin/alpa migrate --project /path/to/game --profile example --apply --replace-claude
```

Claude Code içinde `/studio-start` ile başlayın. Proje kapsamlı konumlar ve hook yapısı, Anthropic'in güncel alt ajan, skill, ayar ve hook belgelerini izler.

Kurulu, mevcut bir projede iki yol vardır:

- `scripts/studio-start.sh` çalıştırın, ya da
- projede `claude`'u başlatıp `start` (veya ayarlı başka bir devam ifadesi) yazın.

Studio Director kayıtlı durumu kaldığı yerden sürdürür ve kuyruktaki ilk uygun görevi çalıştırır.

## Depo haritası

```text
bin/alpa                         taşınabilir başlatıcı
src/alpa_studio/                kurulum, sağlık, iş akışı, panel
templates/project/.claude/      46 ajan, yedi skill, hook'lar, ayarlar, kurallar
templates/project/docs/studio/  kılavuzlar, kararlar, QA, araştırma, güvenlik
profiles/                       example.json; kendi profil JSON'unuzu ekleyin
tests/                          entegrasyon ve güvenlik testleri
tools/usage_scan.py             kendi dökümlerinizden token kullanımını ölçün
docs/                           mimari, durum, denetim, sertifika
```

## Geliştirme ve doğrulama

```sh
python3 scripts/generate_templates.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Üretilen ajan şablonları deterministiktir. Ortak yapılarının kaynağı `scripts/generate_templates.py` dosyasıdır; kurulan her proje bağımsız bir kopya olarak kalır.

## AI Game Studio 0.3.x'ten yükseltme

Alpa Studio 0.4.0'ın eski adı AI Game Studio'ydu (komut: `ags`).

- `ags` kullanımdan kalkmış bir takma ad olarak çalışmaya devam eder: tek satırlık bir uyarı basar, sonra `alpa` gibi davranır.
- Eşleşen `ALPA_*` ortam değişkeni tanımlı değilse `AGS_*` değişkenleri okunur.
- Hâlâ `.ai-game-studio/` klasörü olan bir proje, doğrulanmış bir yedekle `.alpa-studio/`'ya taşınır. Bu, `alpa upgrade --apply` ile ya da projedeki ilk komutta otomatik olur.

Ayrıntılar: [docs/MIGRATION.md](docs/MIGRATION.md).

## Zaten Claude kurulumu olan projeler

Oyun zaten başka bir Claude eklentisi, kendi ajanlarını veya yerel Unity paketlerini kullanıyorsa `alpa migrate` kullanın: önce gözden geçirin, sonra `--apply --replace-claude` verin. Kurmadan önce paket sahipliğini, eklenti adlarını, hook'ları ve onaylı oyun belgelerini karşılaştırın. Açıkça uygulamadan hiçbir şey değiştirilmez.
