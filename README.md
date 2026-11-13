# reels-autopilot — Po Chai / Kreator AI

Pipeline **gratis** dan **otonom** untuk Reels Instagram: riset topik → naskah → TTS → render 9:16 → QC → **ACC di Telegram** → publish ke IG @achmad_radinal94, lalu paket share manual ke profil Facebook Po Chai. Jalan di **GitHub Actions**, tanpa PC/VPS.

Visual: tiga gaya bergantian — **penjelas** (motion graphics + suara), **cerita stickman** (kiasan motivasi, pustaka tetap), dan **kolase scrapbook** (potongan foto berlisensi bebas, mesin tik, piano). Tautan affiliate diatur sendiri di `config/affiliate.yaml` (kosong secara default).

Variable repo **`DRY_RUN=false`** saat pipeline resmi jalan (5 slot/hari). Lokal, default kode tetap aman jika `DRY_RUN` tidak diisi. **`APPROVAL_MODE=required`**: tanpa ACC/OK, job publish tidak menayangkan Reel.

Baca dulu:

1. **[BLUEPRINT.md](BLUEPRINT.md)** — arsitektur, rantai failover, batas gratis yang jujur, kelayakan 5 video/hari.
2. **[SETUP_CHECKLIST.md](SETUP_CHECKLIST.md)** — langkah berurutan, akun mana, siapa yang kerjakan (BRO vs BOT), daftar secret.
3. **[docs/SETUP_STATUS.md](docs/SETUP_STATUS.md)** — status setup terkini (akun, ID, jadwal, sisa pekerjaan).

## Batasan Meta

Jalur utama: Graph API ke IG professional **@achmad_radinal94** (`IG_GRAPH_HOST`, default `graph.facebook.com` / v21.0; token Facebook Login for Business). Meta API tidak bisa posting ke profil pribadi, dan auto-share IG tidak menyala untuk Reel yang dipublish lewat API — setelah tayang, bot mengirim MP4 + caption siap salin ke Telegram untuk di-share ke profil **Po Chai**. Facebook Page tidak dipakai. Token SYSTEM_USER di-health-check mingguan.

## Tes yang sudah jalan di box (12 Nov 2026, WITA)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=src DRY_RUN=true .venv/bin/python -m reels_autopilot sample
PYTHONPATH=src .venv/bin/pytest tests/ -q
```

Sampel uji awal: [`samples/sample_reel.mp4`](samples/sample_reel.mp4)

- 1080×1920, 30 fps, **64,54 detik**, audio AAC (edge-tts, `id-ID-ArdiNeural`)
- Loudness **−14,0 LUFS**, true peak **−0,5 dBTP**, mean **−14,2 dB**
- Catatan koreksi (caption flicker + durasi terlalu panjang, target baru 30–40 dtk / batas 45 dtk): [`docs/TEST_NOTES.md`](docs/TEST_NOTES.md)

Perintah lain: `scout`, `produce`, `publish --slot 1`, `poll`, `run-once`, `refresh-ig-token`, `providers`, `status`, `qc PATH`.

## Akun

- Meta / FB / IG / Business Suite: **radinalachmad@gmail.com**
- GitHub, Gemini, dan layanan non-Meta: **arrowmichael17@gmail.com**
- Telegram bot: **@BotFather** di **@achmadrd**

Repo publik: [MichaelArrow17/reels-autopilot](https://github.com/MichaelArrow17/reels-autopilot). Jangan commit file `.env` atau `.secrets/`.
