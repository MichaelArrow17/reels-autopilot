# SETUP_CHECKLIST — satu kali, lalu otonom

Semua langkah di bawah **belum dikerjakan**. Repo ini hanya berisi kode, di komputer Bot. **Tidak ada akun yang dibuat, tidak ada login, tidak ada push, tidak ada post.**

Legenda:

- **[BRO]** — harus kamu (login, 2FA, persetujuan, ID). Bot tidak bisa menyelesaikan ini tanpa kamu di depan layar.
- **[BOT]** — Bot bisa kerjakan lewat browser / CLI **setelah** kamu izinkan dan, jika perlu, login. *Sekarang tidak dikerjakan.*
- **[SUDAH]** — sudah ada di repo ini.

Akun:

| Keperluan | Akun |
|---|---|
| Facebook, Page, Business Suite, Meta developer app, Instagram @achmad_radinal94 | **radinalachmad@gmail.com** |
| GitHub, Gemini (AI Studio), Groq, OpenRouter, Cloudflare, Hugging Face, Pexels, Pixabay, Unsplash, YouTube Data API, R2 | **arrowmichael17@gmail.com** |
| Bot Telegram | **@BotFather** di Telegram **@achmadrd** |

Jangan tempel token di chat. Jangan pakai kunci orang lain atau yang bocor.

`DRY_RUN` harus tetap `true` sampai tes Reel ke Instagram (API Instagram Login) berhasil.

---

## A. Persiapan Meta — radinalachmad@gmail.com

Jalur utama: **Instagram API with Instagram Login** (`graph.instagram.com`). Profil Facebook menerima Reel lewat **auto-share IG**. Facebook Page bersifat **opsional**, bukan syarat otomasi.

1. **[BRO]** Di Instagram @achmad_radinal94: pastikan akun **Professional** (Creator atau Business).
2. **[BRO]** Aktifkan auto-share Reel IG ke profil Facebook (pengaturan IG / Accounts Center), login radinalachmad@gmail.com.
3. **[BRO, opsional]** Facebook Page “Po Chai” hanya jika nanti ingin publish API langsung ke Page. Bukan wajib.
4. **[BRO]** Uji manual 1 Reel di IG; pastikan muncul juga di profil Facebook jika auto-share aktif.
5. **[BRO]** Buat app di [developers.facebook.com](https://developers.facebook.com) dengan produk **Instagram API with Instagram Login** (bukan Facebook Login for Business sebagai syarat).
6. **[BRO]** Izin (permissions), Standard Access cukup kalau app hanya untuk akun sendiri:
   - Wajib: `instagram_business_basic`, `instagram_business_content_publish`
   - Opsional Page: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`
7. **[BRO]** Generate **long-lived IG User token** (Instagram Login). Catat `IG_USER_ID` dan `IG_ACCESS_TOKEN`. Simpan hanya di Secrets, bukan chat. Token ini di-refresh otomatis setiap bulan (workflow `refresh-ig-token`, butuh `GH_PAT`).
8. **[BRO]** Cek kuota IG: `GET https://graph.instagram.com/{ig-id}/content_publishing_limit?fields=config,quota_usage` (100 vs 50 — **BELUM DIVERIFIKASI**).

## B. Bot Telegram — @achmadrd

9. **[BRO]** Buka @BotFather, `/newbot`, nama misalnya `Po Chai Reels`, username bebas (mis. `pochai_reels_bot`). Simpan token. `/start` ke bot itu dari akun @achmadrd.
10. **[BRO] atau [BOT setelah izin]** Dapatkan `TELEGRAM_CHAT_ID` (angka). Cara: kirim pesan ke bot, lalu `getUpdates`, atau Bot bisa membacanya saat poll pertama (`/start`).

## C. GitHub + compute — arrowmichael17@gmail.com

11. **[BRO]** Login GitHub dengan arrowmichael17. Buat **repo privat dulu atau publik**:
    - **Publik (disarankan untuk 5/hari, menit gratis tanpa batas fair-use).** Video di Releases akan publik (sama seperti Reels). Jangan commit `.env`.
    - **Privat:** lebih tertutup, tapi jatah **≈2.000 menit/bulan** (paket Free, resmi) — mepet untuk 5/hari. Lihat BLUEPRINT bagian 6.
12. **[BRO]** Jangan centang “Add README” kalau mau push bersih, atau biarkan kosong. **Jangan minta Bot push** sampai kamu izinkan eksplisit (tahap ini **tidak di-push**).
13. **[BOT setelah izin]** `git remote` + push isi `/workspace/reels_autopilot`. Aktifkan Actions.
14. **[BRO]** Settings → Secrets and variables → Actions: isi daftar bagian G di bawah. Variables: `DRY_RUN=true`, `APPROVAL_MODE=veto`, `GITHUB_RELEASES_REPO=owner/nama` (jika publik).
15. **[BRO]** Workflow permission: `contents: write` sudah di YAML; untuk GitHub Models, pastikan `models: read` (sudah di YAML).
16. **Cadangan (opsional, nanti):** repo GitHub kedua, atau impor ke GitLab (file `.gitlab-ci.yml` sudah ada). Angka menit GitLab **BELUM DIVERIFIKASI**.

## D. Kunci LLM & TTS — arrowmichael17@gmail.com

Tidak semua wajib. **Minimal: Gemini.** Yang lain = cadangan otomatis. Template lokal selalu ada.

17. **[BRO]** [Google AI Studio](https://aistudio.google.com) → Get API key → `GEMINI_API_KEY`. Cek rate limit di konsol (angka tidak kami salin). Beberapa proyek free bisa minta verifikasi HP — **[BRO]**.
18. **[BRO, opsional]** [Groq console](https://console.groq.com) → API key → `GROQ_API_KEY`.
19. **[BRO, opsional]** GitHub Settings → Developer settings → PAT dengan `models: read`, atau andalkan `GITHUB_TOKEN` di Actions → `GITHUB_MODELS_TOKEN`.
20. **[BRO, opsional]** [OpenRouter](https://openrouter.ai) → kunci, pilih model berakhiran `:free` → `OPENROUTER_API_KEY`.
21. **[BRO, opsional]** Cloudflare dashboard → Workers AI: `CF_ACCOUNT_ID`, `CF_API_TOKEN` (izin Workers AI).
22. **[BRO, opsional]** [Hugging Face](https://huggingface.co) → token → `HF_TOKEN`.
23. **TTS:** edge-tts dan gTTS **tanpa kunci**. **[BOT opsional]** pasang Piper + model Indonesia di runner (`PIPER_BIN`, `PIPER_MODEL`) sebagai cadangan offline.

Jangan daftar layanan yang mewajibkan kartu / KYC kecuali kamu minta (SOP). GCP/Azure TTS free-tier sering butuh billing account — **tidak** dimasukkan ke rantai wajib.

## E. Gambar stok (opsional) — arrowmichael17

Visual utama = stickman lokal (tanpa kunci). Stok hanya latar, **filter lisensi komersial**.

24. **[BRO, opsional]** [Pexels API](https://www.pexels.com/api/) → `PEXELS_API_KEY`.
25. **[BRO, opsional]** [Pixabay API](https://pixabay.com/api/docs/) → `PIXABAY_API_KEY`.
26. **[BRO, opsional]** [Unsplash Developers](https://unsplash.com/developers) → `UNSPLASH_ACCESS_KEY`.
27. Openverse dan Wikimedia **tanpa kunci** (sudah di kode; atribusi otomatis).

## F. Hosting MP4 untuk IG — arrowmichael17

IG **wajib** `video_url` publik (GitHub Releases / R2 / catbox). Facebook Page opsional tidak butuh URL publik (unggah biner).

28. **[BRO]** Kalau repo **publik**: set `GITHUB_RELEASES_REPO=owner/nama`. `GITHUB_TOKEN` otomatis di Actions. Ini jalur primer.
29. **[BRO, opsional]** Cloudflare R2 (tier gratis, **angka BELUM DIVERIFIKASI**): buat bucket + public URL / domain. Isi `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`, `R2_ENDPOINT`.
30. **catbox.moe** tanpa kunci, sudah di rantai sebagai cadangan terakhir (tanpa SLA; cek ToS).

## G. Daftar secret & variable (nama harus sama)

Isi di GitHub Actions Secrets (nilai) dan Variables (yang bukan rahasia). Lokal: salin `.env.example` → `.env`.

### Secrets (wajib untuk go-live, tidak untuk DRY_RUN tes lokal)

| Nama | Akun | Wajib? |
|---|---|---|
| `IG_USER_ID` | radinalachmad | ya, untuk publish IG |
| `IG_ACCESS_TOKEN` | radinalachmad | ya, long-lived Instagram Login token |
| `GH_PAT` | arrowmichael17 | ya, untuk cron refresh token IG (GITHUB_TOKEN Actions tidak bisa menulis secret) |
| `TELEGRAM_BOT_TOKEN` | @achmadrd / BotFather | ya, untuk bot HP |
| `TELEGRAM_CHAT_ID` | @achmadrd | ya, agar pesan sampai |
| `GEMINI_API_KEY` | arrowmichael17 | sangat disarankan (naskah lebih bagus) |
| `FB_PAGE_ID` | radinalachmad | tidak, opsional (publish ke Page) |
| `FB_PAGE_TOKEN` | radinalachmad | tidak, opsional (publish ke Page) |

### Secrets (cadangan, opsional)

`GROQ_API_KEY`, `GITHUB_MODELS_TOKEN`, `OPENROUTER_API_KEY`, `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `HF_TOKEN`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `UNSPLASH_ACCESS_KEY`, `YOUTUBE_API_KEY`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`, `R2_ENDPOINT`.

`GITHUB_TOKEN` disediakan GitHub otomatis — jangan dibuat manual.

### Variables

| Nama | Default | Catatan |
|---|---|---|
| `DRY_RUN` | `true` | Ubah ke `false` **hanya** setelah tes DRAFT sukses |
| `APPROVAL_MODE` | `veto` | `auto` / `veto` / `required` |
| `AUTO_APPROVE_TIMEOUT_MIN` | `45` | |
| `DAILY_QUOTA` | `5` | |
| `META_GRAPH_VERSION` | `v26.0` | sesuai docs yang dikutip playbook; ubah jika deprecated |
| `GITHUB_RELEASES_REPO` | `owner/repo` | untuk URL IG |
| `VIDEO_HOST_CHAIN` | `github_release,r2,catbox` | |
| `GITHUB_MODELS_MODEL` | `openai/gpt-4o-mini` | cek nama resmi saat setup |
| `GEMINI_MODEL` | `gemini-2.0-flash` | |
| `TTS_VOICE` | `id-ID-ArdiNeural` | atau `id-ID-GadisNeural` |

## H. Urutan uji setelah secrets terisi

31. **[BOT atau BRO]** `python -m reels_autopilot providers` — cek rantai.
32. **[BOT atau BRO]** `python -m reels_autopilot sample` — sudah ditest di box (lihat `samples/sample_reel.mp4`).
33. **[BOT atau BRO]** `python -m reels_autopilot scout` — shortlist ke Telegram (kalau token ada).
34. **[BRO]** Di Telegram: `/start`, `/status`. Coba `TOLAK 1` di mode veto.
35. **[BOT setelah izin]** `publish` dengan `video_state=DRAFT` ke **Page** (bukan profil), `DRY_RUN=false` hanya untuk tes itu. Cek hasil di Page.
36. **[BOT setelah izin]** 1 Reel IG uji (butuh URL publik).
37. **[BRO]** Baru kemudian set `DRY_RUN=false` di Actions Variables, biarkan cron jalan. 5 slot: 07:30, 12:00, 17:00, 19:00, 21:00 WITA.

## I. Yang [SUDAH] selesai di repo

- Kode pipeline, router failover, workflow cron, `.gitlab-ci.yml` cadangan.
- `BLUEPRINT.md`, `.env.example`, tes unit, sampel MP4 yang lolos QC.
- **Belum:** akun, secrets, push, publish nyata.
