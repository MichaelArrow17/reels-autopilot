# SETUP_STATUS — reels-autopilot

Status setup per 12 November 2026 (WITA). Dokumen ini merangkum arsitektur yang sudah jalan, akun, ID, jadwal, rantai failover, dan sisa pekerjaan. Tidak berisi password, token, atau kunci API. Bahan untuk PDF operasional nanti.

Repo publik: [MichaelArrow17/reels-autopilot](https://github.com/MichaelArrow17/reels-autopilot). Kode di `/workspace/reels_autopilot`. Secret lokal hanya di `.secrets/` (gitignored, chmod 600).

`DRY_RUN` masih `true`. Belum ada publish nyata ke Instagram.

---

## 1. Arsitektur saat ini

Pipeline otonom, 100% gratis, dijalankan di GitHub Actions (repo publik, tanpa PC/VPS milik bro):

1. **Scout** — kumpulkan topik (Trends, YouTube, Reddit, news RSS, bank evergreen), filter safety, skor, shortlist ke Telegram.
2. **Produce** — naskah (75–100 kata, target 30–40 dtk, batas 45 dtk) → TTS + timestamp kata → render 1080×1920 30 fps + caption karaoke → QC → preview video ke Telegram.
3. **Approval** — mode default `veto`. Bro bisa `TOLAK N`, `/pause`, `/status` dari HP. Bot `@pochai_reels_bot` tidak hidup 24 jam; pesan dibaca saat job Actions (`poll`, serta di awal `produce` / `publish`).
4. **Publish** — host MP4 di URL publik (GitHub Releases → R2 → catbox) → buat container Reels di Graph API → poll `status_code` sampai `FINISHED` → `media_publish` → ambil permalink → kirim ke Telegram, plus catatan `cek FB Po Chai`.

Jalur utama publish adalah **Instagram @achmad_radinal94** (akun Business). Profil Facebook **Po Chai** (~4k teman/pengikut) menerima Reel lewat **auto-share IG**, karena Meta Graph API tidak bisa posting ke profil pribadi. Facebook Page (ShareThis atau Page lain) **tidak dipakai**.

Token yang dipakai sekarang adalah **Facebook Login for Business user token** (prefiks `EAAP`) dari app Meta, bukan token Instagram Login. Token ini:

- **Berjalan** di `graph.facebook.com` v21.0 (`GET /{ig-user-id}?fields=username` mengembalikan `achmad_radinal94`; `content_publishing_limit` quota_usage 0 saat dicek).
- **Tidak berjalan** di `graph.instagram.com` (cannot parse).

Karena itu host Graph IG bisa diatur lewat env/variable `IG_GRAPH_HOST` (default `graph.facebook.com`) dan `IG_GRAPH_VERSION` (default `v21.0`). Publisher memakai alur yang sama: `POST /{ig-user-id}/media` (`media_type=REELS`, `video_url`, `caption`, `share_to_feed=true`) → poll sampai `FINISHED` → `POST /{ig-user-id}/media_publish`.

Auto-share ke profil FB **tidak bisa diverifikasi lewat API**. Setelah tayang, pesan Telegram menyertakan permalink IG (jika ada) dan teks `cek FB Po Chai`.

Default aman:

- Secret IG kosong → publish dilewati (bukan exception); Telegram tetap memberitahu.
- `DRY_RUN=true` → tidak memanggil API Meta, hanya menulis payload (token disensor). Preview Telegram tetap dikirim.

---

## 2. Akun dan identitas (tanpa rahasia)

| Keperluan | Akun / identitas |
|---|---|
| Facebook, Instagram, Meta developer, Business portfolio | **radinalachmad@gmail.com** |
| Profil Facebook tujuan auto-share | **Po Chai** |
| Instagram (tujuan API) | **@achmad_radinal94** (Business) |
| GitHub, Gemini, dan layanan non-Meta | **arrowmichael17@gmail.com** / GitHub **MichaelArrow17** |
| Bot Telegram | **[@pochai_reels_bot](https://t.me/pochai_reels_bot)** di akun **@achmadrd** |
| Chat Telegram yang terhubung | `TELEGRAM_CHAT_ID=7568757522` |

---

## 3. ID Meta yang sudah ada

| Objek | ID / nama | Catatan |
|---|---|---|
| Meta app | **Reels Autopilot RD** — `1119337430807313` | App untuk token dan izin IG |
| Business portfolio | **Po Chai Media** — `1119071857420872` | Portfolio baru, tersambung ke app |
| Akun iklan | **Po Chai Media Ads** | Kosong, tanpa metode pembayaran, tidak dipakai untuk iklan. Hanya syarat jendela token Meta. |
| Instagram user id | `17841451897642254` | @achmad_radinal94 |

Izin token yang sudah diberikan (saat setup): `instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_messages`, `ads_management`, `ads_read`.

Umur token **belum diketahui**. `debug_token` butuh app secret yang belum disimpan. Sampai itu ada, cron hanya menjalankan health check (`GET /{ig-user-id}?fields=username`).

---

## 4. Workflow dan jadwal (WITA = UTC+8)

Semua workflow di `.github/workflows/`. Bisa juga dijalankan manual (`workflow_dispatch`).

| Workflow | Cron (UTC) | Jam WITA | Isi |
|---|---|---|---|
| `scout.yml` | `0 22 * * *` | 06:00 setiap hari | Shortlist topik + antrian slot |
| `produce.yml` | `30 22 * * *` | 06:30 setiap hari | Naskah, TTS, render, QC, preview Telegram |
| `poll.yml` | `0,20,40 22-23 * * *` dan `0,20,40 0 * * *` | 06:00–07:40 dan 08:00–08:40, tiap 20 menit | Baca perintah Telegram (TOLAK / pause / status) |
| `publish.yml` | `30 23`, `0 4`, `0 9`, `0 11`, `0 13` | **07:30, 12:00, 17:00, 19:00, 21:00** | Publish 1 slot (atau dry-run) |
| `refresh-ig-token.yml` | `0 0 1 * *` | tanggal 1, 08:00 | Exchange token jika app secret ada |
| `refresh-ig-token.yml` | `0 1 * * 1` | Senin 09:00 | Health check mingguan (atau exchange jika secret app ada) |

Cadangan compute: `.gitlab-ci.yml` (hanya darurat; menit GitLab belum diverifikasi).

Setelah `produce` / `publish` / `poll`, state JSON di-commit otomatis ke `main` (tanpa file media).

---

## 5. Secret dan variable GitHub Actions

Repo: `MichaelArrow17/reels-autopilot`. Nilai tidak dicatat di sini.

### Secrets yang sudah diisi

`GEMINI_API_KEY`, `GH_PAT`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `IG_USER_ID`, `IG_ACCESS_TOKEN`.

`GH_PAT` adalah fine-grained PAT (Secrets / Variables / Workflows / Contents RW pada repo ini). Dipakai menulis ulang `IG_ACCESS_TOKEN` saat exchange berhasil. `GITHUB_TOKEN` otomatis Actions **tidak** bisa menulis secret.

### Variables yang sudah diisi

| Nama | Nilai |
|---|---|
| `DRY_RUN` | `true` |
| `IG_GRAPH_HOST` | `graph.facebook.com` |

### Belum diisi (sengaja / masih menunggu)

| Nama | Fungsi |
|---|---|
| `FB_APP_ID` / `FB_APP_SECRET` | Auto-refresh (`fb_exchange_token`) + `debug_token` + alert jika token invalid atau sisa umur &lt; 10 hari |
| `FB_PAGE_ID` / `FB_PAGE_TOKEN` | Tidak dipakai (Page bukan target) |
| Cadangan LLM/gambar/R2 | Opsional; rantai tetap jalan tanpa mereka |

---

## 6. Rantai failover

Router selalu mencoba primer dulu. Jika kuota/429, provider masuk cooldown lalu cadangan dipakai; setelah reset, primer dicoba lagi. Status di `data/provider_status.json`.

| Kategori | Urutan |
|---|---|
| LLM | Gemini → Groq → GitHub Models → OpenRouter `:free` → Cloudflare Workers AI → Hugging Face → template lokal |
| TTS | edge-tts (`id-ID-ArdiNeural`) → gTTS → Piper → espeak-ng |
| Gambar | Pexels → Pixabay → Unsplash → Openverse (komersial) → Wikimedia (tanpa CC BY-SA) → stickman lokal |
| Hosting MP4 (wajib URL publik untuk IG) | GitHub Releases → Cloudflare R2 → catbox.moe |
| Topik | union paralel: Google Trends ID, YouTube, Reddit, news RSS, bank evergreen |
| Compute | GitHub Actions repo publik (primer) → repo GitHub kedua → GitLab CI (darurat) |

Kunci API hanya milik akun sendiri (arrowmichael17 / radinalachmad). Tidak memakai kunci bocor atau pihak ketiga.

QC: resolusi, fps, audio, durasi (batas keras 45 dtk), LUFS, timing caption (chunk 2–4 kata, maju monotik, min 0,6 dtk). Gerbang `qc.pre_publish_gate` menolak tayang jika durasi atau caption gagal. Catatan uji awal: `docs/TEST_NOTES.md`.

---

## 7. Perilaku Telegram

- Preview produksi: video + teks slot, judul, jam tayang, cara `TOLAK N`.
- Setelah publish nyata: permalink IG (jika berhasil diambil) + `cek FB Po Chai`.
- Dry-run publish: status `dry_published` + `cek FB Po Chai` (tanpa permalink, karena API Meta tidak dipanggil).
- Alert token: hanya jika health check gagal, token invalid, `debug_token` gagal, atau sisa umur &lt; 10 hari (yang tiga terakhir butuh app secret).
- Bot tidak membalas instan di luar jendela poll/job.

---

## 8. Yang sudah diverifikasi

- App Meta, portfolio Po Chai Media, IG @achmad_radinal94 sebagai tester, dan akun iklan kosong tanpa pembayaran sudah dibuat.
- Token user Facebook Login for Business merespons di `graph.facebook.com` v21.0; username dan kuota publish terbaca.
- Telegram chat id sudah tertaut; `/start` dari bro sudah masuk.
- Dry-run produce di GitHub Actions sudah pernah sukses (Reel ±34,5 dtk, QC lolos, Gemini dipakai).
- Tes unit (termasuk host Graph, skip secret, permalink, health check, exchange, alert kedaluwarsa) ada di `tests/`.

---

## 9. Sisa pekerjaan

1. **App secret Meta** — simpan `FB_APP_SECRET` (dan `FB_APP_ID=1119337430807313`) ke GitHub Secrets agar cron bisa `fb_exchange_token`, menulis ulang `IG_ACCESS_TOKEN` lewat `GH_PAT`, dan `debug_token` (alert jika invalid atau sisa &lt; 10 hari). Tanpa ini, cron hanya health check.
2. **Umur token belum diketahui** sampai langkah 1 selesai. Jika token kadaluarsa sebelum itu, perlu generate ulang di dashboard Meta (tanpa data bayar/KYC).
3. **Go-live** — setelah satu tes publish nyata sukses (permalink IG muncul, Reel sampai ke @achmad_radinal94, dan auto-share terlihat di profil FB Po Chai), baru set variable `DRY_RUN=false`. Jangan ubah lebih awal.
4. **Pastikan auto-share IG → profil FB Po Chai aktif** di pengaturan Instagram / Accounts Center (cek manual; API tidak bisa memastikan).
5. **PDF operasional** — rangkuman alur, layanan, akun, jadwal, cadangan kuota, dan perbaikan, tanpa token. Dokumen ini menjadi bahannya.
6. **Opsional:** isi cadangan LLM/gambar/R2 jika ingin rantai lebih tebal; Piper offline di runner; Page Facebook tetap tidak diperlukan.

Tidak ada KYC, deposit, atau upgrade berbayar pada setup ini. Akun iklan tetap kosong dan tanpa metode bayar.
