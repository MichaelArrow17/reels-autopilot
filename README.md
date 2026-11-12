# reels-autopilot — Po Chai / Kreator AI

Pipeline **gratis** dan **otonom** untuk Reels Instagram (auto-share ke profil Facebook): riset topik → naskah → TTS → render 9:16 → QC → (opsional) veto di Telegram → publish. Jalan di **GitHub Actions**, tanpa PC/VPS.

Default **`DRY_RUN=true`**: tidak ada yang diposting.

Baca dulu:

1. **[BLUEPRINT.md](BLUEPRINT.md)** — arsitektur, rantai failover, batas gratis yang jujur, kelayakan 5 video/hari.
2. **[SETUP_CHECKLIST.md](SETUP_CHECKLIST.md)** — langkah berurutan, akun mana, siapa yang kerjakan (BRO vs BOT), daftar secret.

## Batasan Meta

Jalur utama: **Instagram API with Instagram Login** (`graph.instagram.com`) ke IG professional **@achmad_radinal94**. Profil Facebook menerima Reel lewat **auto-share IG**. Facebook Page bersifat **opsional** (bukan syarat otomasi). Token IG jangka panjang di-refresh bulanan (secret `GH_PAT`).

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
