# reels-autopilot — Po Chai / Kreator AI

Pipeline **gratis** dan **otonom** untuk Reels Facebook Page + Instagram: riset topik → naskah → TTS → render 9:16 → QC → (opsional) veto di Telegram → publish. Jalan di **GitHub Actions**, tanpa PC/VPS.

Default **`DRY_RUN=true`**: tidak ada yang diposting.

Baca dulu:

1. **[BLUEPRINT.md](BLUEPRINT.md)** — arsitektur, rantai failover, batas gratis yang jujur, kelayakan 5 video/hari.
2. **[SETUP_CHECKLIST.md](SETUP_CHECKLIST.md)** — langkah berurutan, akun mana, siapa yang kerjakan (BRO vs BOT), daftar secret.

## Batasan Meta

Graph API **hanya** bisa publish Reels ke **Facebook Page**, bukan ke profil pribadi “Po Chai”. Rencana: buat Page “Po Chai” di **radinalachmad@gmail.com**, IG @achmad_radinal94 ke Creator/Business, tautkan ke Page.

## Tes yang sudah jalan di box (12 Nov 2026, WITA)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=src DRY_RUN=true .venv/bin/python -m reels_autopilot sample
PYTHONPATH=src .venv/bin/pytest tests/ -q
```

Sampel: [`samples/sample_reel.mp4`](samples/sample_reel.mp4)

- 1080×1920, 30 fps, **64,54 detik**, audio AAC (edge-tts, `id-ID-ArdiNeural`)
- Loudness **−14,0 LUFS**, true peak **−0,5 dBTP**, mean **−14,2 dB**
- QC: lolos, tanpa error/peringatan

Perintah lain: `scout`, `produce`, `publish --slot 1`, `poll`, `run-once`, `providers`, `status`, `qc PATH`.

## Akun

- Meta / FB / IG / Business Suite: **radinalachmad@gmail.com**
- GitHub, Gemini, dan layanan non-Meta: **arrowmichael17@gmail.com**
- Telegram bot: **@BotFather** di **@achmadrd**

Repo ini **belum di-push**. Jangan commit file `.env`.
