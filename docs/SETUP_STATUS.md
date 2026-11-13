# SETUP_STATUS — reels-autopilot

Status setup per 13 November 2026 (WITA). Dokumen ini merangkum arsitektur yang sudah jalan, akun, ID, jadwal, rantai failover, dan sisa pekerjaan. Tidak berisi password, token, atau kunci API. Bahan untuk PDF operasional nanti.

Repo publik: [MichaelArrow17/reels-autopilot](https://github.com/MichaelArrow17/reels-autopilot). Kode di `/workspace/reels_autopilot`. Secret lokal hanya di `.secrets/` (gitignored, chmod 600).

`DRY_RUN` diubah ke `false` setelah tes publish nyata 12 November 2026 (WITA). Mode approval: `required` (ACC di Telegram wajib sebelum Reel di-publish ke IG).

---

## 1. Arsitektur saat ini

Pipeline otonom, 100% gratis, dijalankan di GitHub Actions (repo publik, tanpa PC/VPS milik bro):

1. **Scout** — kumpulkan topik (Trends, YouTube, Reddit, news RSS, bank evergreen), filter safety, skor, shortlist ke Telegram.
2. **Produce** — naskah (75–100 kata, target 30–40 dtk, batas 45 dtk) → TTS + timestamp kata → render 1080×1920 30 fps + caption karaoke → QC → preview video ke Telegram.
3. **Approval** — mode `required`. Setelah preview, bro membalas `OK` / `ACC N` (atau `OK 1 2 3 4 5`) supaya slot boleh tayang. `TOLAK N`, `/pause`, `/status` tetap berlaku. Tanpa ACC, job publish melewatkan slot itu. Bot `@pochai_reels_bot` tidak hidup 24 jam; pesan dibaca saat job Actions (`poll` pagi, serta di awal `produce` / `publish`). Produksi tetap jalan dari shortlist; ACC hanya menahan **publish**.
4. **Publish IG** — host MP4 di URL publik (GitHub Releases → R2 → catbox) → buat container Reels di Graph API → poll `status_code` sampai `FINISHED` → `media_publish` → ambil permalink.
5. **Handoff FB (semi-otomatis)** — setelah IG sukses, bot mengirim 2 pesan ke Telegram: (a) file MP4 (`sendVideo`, `supports_streaming=true`; jika &gt;50 MB jatuh ke `sendDocument` atau tautan GitHub Releases) bercaption `Siap share ke FB Po Chai`; (b) caption siap salin (blok `<pre><code>`) + cara share + permalink IG. Gagal kirim Telegram di-retry sekali, lalu hanya di-log — publish IG tidak dibatalkan.

Jalur utama publish API adalah **Instagram @achmad_radinal94** (akun Business). Profil Facebook **Po Chai** (~4k teman/pengikut) **tidak bisa** ditarget lewat Graph API: Reels Publishing API hanya untuk Facebook Page, bukan profil pribadi ([dokumentasi Meta](https://developers.facebook.com/docs/video-api/guides/reels-publishing/)). Facebook Page (ShareThis atau Page lain) **tidak dipakai**, sesuai keputusan bro.

Auto-share native IG → Facebook juga **tidak menyala** untuk Reel yang dipublish lewat API. Ini keterbatasan sisi Instagram, sama seperti yang dicatat Later: meskipun auto-push ke Facebook aktif di akun, fitur itu tidak bekerja saat auto-publish API ([Later Help](https://help.later.com/hc/en-us/articles/360042869094-Will-My-Instagram-Posts-be-Automatically-Shared-to-Facebook)). Karena itu, setelah tiap Reel IG tayang, bro membagikan manual ke profil Po Chai dari paket Telegram (tahan video → Bagikan/Share → Facebook → Reels, tempel caption, Bagikan).

Token yang dipakai sekarang adalah **Facebook Login for Business user token** (prefiks `EAAP`) dari app Meta, bukan token Instagram Login. Token ini:

- **Berjalan** di `graph.facebook.com` v21.0 (`GET /{ig-user-id}?fields=username` mengembalikan `achmad_radinal94`; `content_publishing_limit` quota_usage 0 saat dicek).
- **Tidak berjalan** di `graph.instagram.com` (cannot parse).

Karena itu host Graph IG bisa diatur lewat env/variable `IG_GRAPH_HOST` (default `graph.facebook.com`) dan `IG_GRAPH_VERSION` (default `v21.0`). Publisher memakai alur yang sama: `POST /{ig-user-id}/media` (`media_type=REELS`, `video_url`, `caption`, `share_to_feed=true`) → poll sampai `FINISHED` → `POST /{ig-user-id}/media_publish`.

Karena auto-share API tidak jalan dan API tidak bisa memverifikasi profil pribadi, paket handoff Telegram menggantikan baris lama `cek FB Po Chai`.

Default aman:

- Secret IG kosong → publish dilewati (bukan exception); Telegram tetap memberitahu.
- `DRY_RUN=true` → tidak memanggil API Meta, hanya menulis payload (token disensor). Preview Telegram tetap dikirim.

---

## 2. Akun dan identitas (tanpa rahasia)

| Keperluan | Akun / identitas |
|---|---|
| Facebook, Instagram, Meta developer, Business portfolio | **radinalachmad@gmail.com** |
| Profil Facebook tujuan share manual | **Po Chai** |
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

Token saat ini berjenis **SYSTEM_USER** dan tidak kedaluwarsa. Cron mingguan tetap health check; `debug_token` tersedia karena app secret sudah tersimpan.

---

## 4. Workflow dan jadwal (WITA = UTC+8)

Semua workflow di `.github/workflows/`. Bisa juga dijalankan manual (`workflow_dispatch`).

| Workflow | Cron (UTC) | Jam WITA | Isi |
|---|---|---|---|
| `scout.yml` | `0 22 * * *` | 06:00 setiap hari | Shortlist topik + antrian slot |
| `produce.yml` | `30 22 * * *` | 06:30 setiap hari | Naskah, TTS, render, QC, preview Telegram |
| `poll.yml` | `0,20,40 22-23 * * *` dan `0,20,40 0 * * *` | 06:00–07:40 dan 08:00–08:40, tiap 20 menit | Baca perintah Telegram (ACC / OK / TOLAK / pause / status). ACC di luar jendela ini dibaca di awal job `publish` |
| `publish.yml` | `30 23`, `0 4`, `0 9`, `0 11`, `0 13` | **07:30, 12:00, 17:00, 19:00, 21:00** | Publish 1 slot (atau dry-run) |
| `refresh-ig-token.yml` | `0 0 1 * *` | tanggal 1, 08:00 | Exchange token jika app secret ada |
| `refresh-ig-token.yml` | `0 1 * * 1` | Senin 09:00 | Health check mingguan (atau exchange jika secret app ada) |

Cadangan pemicu jadwal: cron-job.org (akun arrowmichael17, folder `reels-autopilot`).
Job memanggil `workflow_dispatch` di jam WITA yang sama (timezone Asia/Makassar, bukan Jakarta).
Daftar id ada di `docs/CRON_JOB_ORG.md`. Guard idempoten di workflow mencegah double-publish
jika cron GitHub dan cron-job.org terpicu bersama. PAT pemicu: `CRON_DISPATCH_PAT`
(fine-grained, Actions RW pada repo ini saja, **kedaluwarsa 11 Februari 2027**).
Nilai token hanya di `.secrets/cron_dispatch.env` (gitignored), bukan di dokumen ini.

Cadangan compute: `.gitlab-ci.yml` (hanya darurat; menit GitLab belum diverifikasi).

Setelah `produce` / `publish` / `poll`, state JSON di-commit otomatis ke `main` (tanpa file media).

---

## 5. Secret dan variable GitHub Actions

Repo: `MichaelArrow17/reels-autopilot`. Nilai tidak dicatat di sini.

### Secrets yang sudah diisi

`GEMINI_API_KEY`, `GH_PAT`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `IG_USER_ID`, `IG_ACCESS_TOKEN`.

`GH_PAT` adalah fine-grained PAT (Secrets / Variables / Workflows / Contents RW pada repo ini). Dipakai menulis ulang `IG_ACCESS_TOKEN` saat exchange berhasil. `GITHUB_TOKEN` otomatis Actions **tidak** bisa menulis secret.

Pemicu cron-job.org **tidak** memakai `GH_PAT`. Nama secret lokal: `CRON_DISPATCH_PAT`
(Actions: Read and write, hanya repo ini) dan `CRONJOB_API_KEY`.
`CRON_DISPATCH_PAT` **kedaluwarsa 11 Februari 2027** — perpanjang sebelum tanggal itu.
Kedua nilai hanya ada di `.secrets/cron_dispatch.env`, tidak di GitHub Actions secrets, dan tidak dicatat di sini.

### Variables yang sudah diisi

| Nama | Nilai |
|---|---|
| `DRY_RUN` | `false` (go-live 12 Nov 2026 malam WITA) |
| `IG_GRAPH_HOST` | `graph.facebook.com` |
| `APPROVAL_MODE` | `required` |

### Sudah diisi belakangan

`FB_APP_ID`, `FB_APP_SECRET` — untuk health check / `debug_token`. Token yang dipakai adalah **SYSTEM_USER** Facebook Login for Business (tidak kedaluwarsa); cron mingguan tetap memantau. Jika Meta memutus token, alert masuk ke Telegram.

### Sengaja tidak diisi

| Nama | Fungsi |
|---|---|
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

- Preview produksi (satu pesan): MP4 + **caption final yang akan di-publish ke IG** (blok `<pre><code>` siap salin ke IG/FB) + cara singkat share ke FB Po Chai + instruksi ACC/TOLAK. Caption itu disimpan di state dan dipublish apa adanya setelah ACC (tidak digenerate ulang).
- Setelah publish IG nyata: **satu catatan singkat** “sudah tayang” + permalink IG. File dan caption tidak dikirim ulang (sudah ada di preview).
- Dry-run publish: status `dry_published` saja, tanpa paket share FB (karena API Meta tidak dipanggil).
- Alert token: hanya jika health check gagal, token invalid, `debug_token` gagal, atau sisa umur &lt; 10 hari.
- Bot tidak membalas instan di luar jendela poll/job.

---

## 8. Yang sudah diverifikasi

- App Meta, portfolio Po Chai Media, IG @achmad_radinal94 sebagai tester, dan akun iklan kosong tanpa pembayaran sudah dibuat.
- Token user Facebook Login for Business merespons di `graph.facebook.com` v21.0; username dan kuota publish terbaca.
- Telegram chat id sudah tertaut; `/start` dari bro sudah masuk.
- Dry-run produce di GitHub Actions sudah pernah sukses (Reel ±34,5 dtk lalu tes 37 dtk, QC lolos).
- Tes publish nyata satu Reel ke @achmad_radinal94 sukses pada 12 Nov 2026 22:38 WITA: https://www.instagram.com/reel/DfpSYK-CuMW/ (media `18418112578086444`). Auto-share ke profil FB Po Chai **tidak menyala**; handoff manual lewat Telegram menggantikannya.
- Tes unit (termasuk host Graph, skip secret, permalink, health check, exchange, alert kedaluwarsa, caption cadangan, paket handoff FB) ada di `tests/`.

---

## 9. Sisa pekerjaan

1. **Share manual Reel uji** ke profil FB Po Chai dari paket Telegram (sudah disiapkan setelah tes publish).
2. **PDF operasional** — rangkuman alur, layanan, akun, jadwal, cadangan kuota, dan perbaikan, tanpa token. Dokumen ini menjadi bahannya.
3. **Opsional:** isi cadangan LLM/gambar/R2 jika ingin rantai lebih tebal; Piper offline di runner; Page Facebook tetap tidak diperlukan.

Tidak ada KYC, deposit, atau upgrade berbayar pada setup ini. Akun iklan tetap kosong dan tanpa metode bayar.

---

## 10. Gaya visual (mulai 14 November 2026)

Dua gaya bergantian, dipilih dari topik plus rotasi agar batch harian beragam. Tercatat di state (`style`, `style_history`).

- **Penjelas** — motion graphics 2D (teks kinetik sinkron kata, ikon vektor, perbandingan, counter, penanda bab 01/05, SFX). Untuk topik info: teknologi, AI, keuangan, tips. Suara TTS edge-tts (cadangan GadisNeural / ArdiNeural) dengan WordBoundary.
- **Cerita stickman** — lingkungan dan karakter dari pustaka tetap (bukan kode yang ditulis LLM per video). Gemini hanya mengisi JSON storyboard; jika tidak valid, templat aman dipakai. Untuk konten motivasi/kiasan, 20–30 detik, tanpa voice-over (ambien + SFX). Lingkungan: underwater, staircase, mountain, road, office, scale.

Safeguard lama tetap: caption_guard, gerbang QC, idempotensi, preview Telegram satu pesan dengan caption final, tanpa angka karangan.

**Affiliate:** `config/affiliate.yaml` kosong secara default (`enabled: false`). Deng Aji yang mengatur produk, kata kunci, dan CTA (mis. "Cek link di bio."). Tautan tidak disisipkan ke caption kecuali kelak `insert_url: true` (default false). Bot tidak mengarang tautan.

Sampel uji dikirim ke Telegram sebagai **SAMPEL UJI – bukan untuk diposting**, tidak masuk antrian ACC/publish.
