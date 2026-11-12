"""Katalog rantai failover + batas tier gratis.

Angka yang tidak dicek langsung di halaman resmi pada 12 Nov 2026 (WITA)
ditandai verified=False (BELUM DIVERIFIKASI). Jangan dianggap jaminan kuota.
Router memakai sinyal error (HTTP 429, RESOURCE_EXHAUSTED, Retry-After)
bukan angka di sini, untuk memutuskan cooldown.
"""

from __future__ import annotations

# reset: "pacific_midnight" | "hourly" | "monthly_billing" | "unknown" | "n/a"
# always_available: tidak butuh kunci, atau fallback lokal

CATALOG: dict[str, list[dict]] = {
    "llm": [
        {
            "id": "gemini",
            "name": "Google Gemini (AI Studio / Gemini API)",
            "akun": "arrowmichael17@gmail.com",
            "env": ["GEMINI_API_KEY"],
            "gratis": True,
            "limits": (
                "Ada free tier. Kuota per model (RPM / TPM / RPD) ditampilkan di "
                "Google AI Studio dan berubah menurut tier. RPD reset pukul 00:00 "
                "waktu Pacific (resmi, docs diperbarui 28 Okt 2026). Angka RPD "
                "spesifik model TIDAK saya salin di sini karena halaman resmi "
                "menyuruh melihat konsol langsung."
            ),
            "verified": True,
            "verified_note": "Fakta adanya free tier + reset midnight Pacific: docs resmi. Angka RPM/RPD: tidak dicantumkan (lihat AI Studio).",
            "reset": "pacific_midnight",
            "quota_signals": ["429", "RESOURCE_EXHAUSTED", "quota", "rate limit"],
        },
        {
            "id": "groq",
            "name": "Groq (OpenAI-compatible, Llama dsb.)",
            "akun": "arrowmichael17@gmail.com",
            "env": ["GROQ_API_KEY"],
            "gratis": True,
            "limits": (
                "Ada free tier dengan batas RPM/RPD/TPD yang terlihat di Groq console. "
                "Angka pasti berubah menurut model. BELUM DIVERIFIKASI per 12 Nov 2026 "
                "(halaman pricing tidak dibuka saat penulisan)."
            ),
            "verified": False,
            "reset": "unknown",
            "quota_signals": ["429", "rate_limit", "quota", "insufficient_quota"],
        },
        {
            "id": "github_models",
            "name": "GitHub Models (resmi, paket Free)",
            "akun": "arrowmichael17@gmail.com",
            "env": ["GITHUB_MODELS_TOKEN atau GITHUB_TOKEN"],
            "gratis": True,
            "limits": (
                "Layanan resmi GitHub: inference chat (OpenAI-compatible) dengan akun GitHub Free. "
                "Di Actions, GITHUB_TOKEN bisa dipakai jika permission models: read diaktifkan. "
                "Rate-limit per model/akun ditampilkan di docs GitHub Models dan berubah. "
                "Angka RPM/RPD pasti BELUM DIVERIFIKASI per 12 Nov 2026. Tidak perlu kartu. "
                "Jangan pakai kunci orang lain — hanya token akun sendiri."
            ),
            "verified": False,
            "verified_note": "Keberadaan layanan resmi + akses dengan akun GitHub: diketahui publik. Angka kuota: cek docs/console.",
            "reset": "unknown",
            "quota_signals": ["429", "403", "rate", "quota"],
        },
        {
            "id": "openrouter",
            "name": "OpenRouter (model :free)",
            "akun": "arrowmichael17@gmail.com",
            "env": ["OPENROUTER_API_KEY"],
            "gratis": True,
            "limits": (
                "Model dengan akhiran :free bisa dipanggil tanpa kredit berbayar, "
                "tapi RPM rendah dan daftar model sering berubah. Batas pasti "
                "BELUM DIVERIFIKASI. Beberapa model :free kadang memerlukan "
                "sisa kredit $0 yang tetap dibatasi rate-limit."
            ),
            "verified": False,
            "reset": "unknown",
            "quota_signals": ["429", "rate-limit", "quota", "insufficient"],
        },
        {
            "id": "cloudflare",
            "name": "Cloudflare Workers AI",
            "akun": "arrowmichael17@gmail.com",
            "env": ["CF_ACCOUNT_ID", "CF_API_TOKEN"],
            "gratis": True,
            "limits": (
                "Workers AI punya alokasi gratis (neuron/unit harian pada paket Free). "
                "Angka '10.000 neurons/hari' beredar di sumber lama — "
                "BELUM DIVERIFIKASI per 12 Nov 2026. Cek dashboard Cloudflare."
            ),
            "verified": False,
            "reset": "unknown",
            "quota_signals": ["429", "402", "quota", "exceeded"],
        },
        {
            "id": "huggingface",
            "name": "Hugging Face Inference",
            "akun": "arrowmichael17@gmail.com",
            "env": ["HF_TOKEN"],
            "gratis": True,
            "limits": (
                "Inference API/router sering berubah (antrian, model dipindah ke "
                "penyedia berbayar, rate-limit ketat). Jangan andalkan sebagai primer. "
                "Batas pasti BELUM DIVERIFIKASI."
            ),
            "verified": False,
            "reset": "unknown",
            "quota_signals": ["429", "503", "rate", "quota", "overloaded"],
        },
        {
            "id": "template",
            "name": "Template lokal (tanpa API)",
            "akun": "—",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": "Tidak terbatas. Kualitas naskah lebih kaku, tidak mengarang angka.",
            "verified": True,
            "reset": "n/a",
            "quota_signals": [],
        },
    ],
    "tts": [
        {
            "id": "edge_tts",
            "name": "edge-tts (Microsoft Edge Read Aloud, tidak resmi)",
            "akun": "— (tanpa kunci)",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": (
                "Tidak ada kuota resmi yang dipublikasikan karena ini API tidak resmi "
                "ke layanan Read Aloud Microsoft. Bisa dibatasi, berubah, atau putus "
                "kapan saja. Tidak ada SLA. Untuk produksi jangka panjang, pertimbangkan "
                "Azure TTS berbayar atau Piper offline."
            ),
            "verified": True,
            "verified_note": "Sifat tidak resmi + tanpa kuota resmi: fakta. Angka rate-limit: tidak ada yang resmi.",
            "reset": "unknown",
            "quota_signals": ["429", "403", "503"],
        },
        {
            "id": "gtts",
            "name": "gTTS (Google Translate TTS, tidak resmi)",
            "akun": "— (tanpa kunci)",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": (
                "Tidak resmi, tanpa kuota publik. Google bisa memblokir. Tidak ada "
                "timestamp per kata (pipeline memperkirakan merata). Kualitas di bawah edge-tts."
            ),
            "verified": True,
            "reset": "unknown",
            "quota_signals": ["429", "403", "503"],
        },
        {
            "id": "piper",
            "name": "Piper TTS (offline, open source)",
            "akun": "— (biner + model di runner)",
            "env": ["PIPER_MODEL"],
            "gratis": True,
            "limits": (
                "Sepenuhnya offline, tanpa kuota. Perlu mengunduh biner Piper dan "
                "model suara Indonesia (lisensi per model, biasanya MIT/open). "
                "Kualitas tergantung model. Tidak butuh jaringan saat sintetis."
            ),
            "verified": True,
            "reset": "n/a",
            "quota_signals": [],
        },
        {
            "id": "espeak",
            "name": "espeak-ng (offline, robotik)",
            "akun": "— (paket sistem)",
            "env": [],
            "gratis": True,
            "limits": "Tanpa kuota. Suara robotik, terakhir di rantai, hanya agar audio tetap ada.",
            "verified": True,
            "reset": "n/a",
            "quota_signals": [],
        },
    ],
    "images": [
        {
            "id": "pexels",
            "name": "Pexels API",
            "akun": "arrowmichael17@gmail.com",
            "env": ["PEXELS_API_KEY"],
            "gratis": True,
            "limits": (
                "API gratis dengan kunci. Angka yang beredar (mis. 200 req/jam atau "
                "20.000/bulan) berasal dari sumber lama — BELUM DIVERIFIKASI per "
                "12 Nov 2026. Wajib atribusi sesuai lisensi Pexels. Hanya foto yang "
                "memang bebas dipakai."
            ),
            "verified": False,
            "reset": "hourly",
            "quota_signals": ["429", "403"],
        },
        {
            "id": "pixabay",
            "name": "Pixabay API",
            "akun": "arrowmichael17@gmail.com",
            "env": ["PIXABAY_API_KEY"],
            "gratis": True,
            "limits": (
                "API gratis dengan kunci. Rate-limit (mis. 100 req/60 dtk) "
                "BELUM DIVERIFIKASI per 12 Nov 2026. Wajib ikuti Ketentuan Pixabay."
            ),
            "verified": False,
            "reset": "hourly",
            "quota_signals": ["429"],
        },
        {
            "id": "unsplash",
            "name": "Unsplash API",
            "akun": "arrowmichael17@gmail.com",
            "env": ["UNSPLASH_ACCESS_KEY"],
            "gratis": True,
            "limits": (
                "Demo/production free: angka yang sering dikutip 50 request/jam. "
                "BELUM DIVERIFIKASI di halaman resmi pada 12 Nov 2026. Wajib atribusi "
                "fotografer + Unsplash. Jangan hotlink sembarangan; unduh lalu cache."
            ),
            "verified": False,
            "reset": "hourly",
            "quota_signals": ["403", "429"],
        },
        {
            "id": "openverse",
            "name": "Openverse API (WordPress, Creative Commons, resmi)",
            "akun": "— (tanpa kunci; registrasi opsional untuk limit lebih tinggi)",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": (
                "API resmi Openverse (openverse.org) untuk karya berlisensi terbuka. "
                "Tanpa kunci ada rate-limit anonim; angka pasti BELUM DIVERIFIKASI. "
                "Wajib atribusi sesuai lisensi tiap gambar. Hanya pakai lisensi yang "
                "memperbolehkan penggunaan komersial jika Reels dimonetisasi "
                "(filter license_type=commercial kalau tersedia)."
            ),
            "verified": False,
            "reset": "hourly",
            "quota_signals": ["429", "403"],
        },
        {
            "id": "wikimedia",
            "name": "Wikimedia Commons API (resmi, tanpa kunci)",
            "akun": "— (wajib User-Agent deskriptif, kebijakan resmi Wikimedia)",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": (
                "API resmi, tanpa kunci, gratis. Kebijakan: User-Agent yang jelas, "
                "jangan membantai endpoint, hormati lisensi tiap berkas (banyak CC BY-SA: "
                "wajib atribusi; cek apakah cocok untuk Reels monetisasi). "
                "Tidak ada kuota angka tetap yang saya kutip — BELUM DIVERIFIKASI selain "
                "aturan rate-limit umum Wikimedia."
            ),
            "verified": False,
            "reset": "hourly",
            "quota_signals": ["429", "403"],
        },
        {
            "id": "local",
            "name": "Gambar lokal / stickman (Pillow)",
            "akun": "—",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": "Tidak terbatas. Ini jalur visual utama (gaya stickman Po Chai).",
            "verified": True,
            "reset": "n/a",
            "quota_signals": [],
        },
    ],
    "topics": [
        {
            "id": "google_trends_rss",
            "name": "Google Trends RSS geo=ID",
            "akun": "—",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": "RSS publik, tanpa kunci. Dites 12 Nov 2026 di playbook. Tidak ada kuota resmi; bisa 429 jika dipanggil terlalu sering.",
            "verified": True,
            "reset": "unknown",
            "quota_signals": ["429"],
        },
        {
            "id": "youtube_autocomplete",
            "name": "YouTube autocomplete (tidak resmi)",
            "akun": "—",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": "Endpoint tidak resmi, bisa berubah/putus. Dites jalan di playbook (12 Nov 2026) untuk 'cara pakai ai'.",
            "verified": True,
            "reset": "unknown",
            "quota_signals": ["429"],
        },
        {
            "id": "youtube_api",
            "name": "YouTube Data API v3 mostPopular ID",
            "akun": "arrowmichael17@gmail.com",
            "env": ["YOUTUBE_API_KEY"],
            "gratis": True,
            "limits": "Kuota default 10.000 unit/hari (resmi). videos.list = 1 unit. search.list punya jatah terpisah 100 call/hari (playbook, dari docs resmi).",
            "verified": True,
            "reset": "pacific_midnight",
            "quota_signals": ["403", "429", "quotaExceeded"],
        },
        {
            "id": "reddit_rss",
            "name": "Reddit RSS (r/ChatGPT, r/artificial, r/singularity)",
            "akun": "—",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": (
                "RSS publik tanpa OAuth. Reddit sering 403 tanpa User-Agent. "
                "Bukan Data API resmi (yang wajib izin Responsible Builder). "
                "Pakai hemat, jangan scrap massal."
            ),
            "verified": True,
            "reset": "unknown",
            "quota_signals": ["403", "429"],
        },
        {
            "id": "news_rss",
            "name": "News RSS (Google News ID, CNN Tekno, The Verge, dsb.)",
            "akun": "—",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": "RSS publik. Tidak ada kuota resmi; sumber bisa memblokir UA kosong atau traffic tinggi.",
            "verified": True,
            "reset": "unknown",
            "quota_signals": ["403", "429"],
        },
        {
            "id": "evergreen_bank",
            "name": "Bank topik evergreen (lokal)",
            "akun": "—",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": "Tanpa kuota. Dipakai mengisi sisa kuota harian jika tren kurang relevan.",
            "verified": True,
            "reset": "n/a",
            "quota_signals": [],
        },
    ],
    "hosting": [
        {
            "id": "github_release",
            "name": "GitHub Releases (repo publik)",
            "akun": "arrowmichael17@gmail.com",
            "env": ["GITHUB_RELEASES_REPO", "GITHUB_TOKEN"],
            "gratis": True,
            "limits": (
                "Cocok sebagai URL publik untuk IG Reels. Repo publik, aset rilis "
                "bisa diunduh siapa saja (video memang akan publik di FB/IG). "
                "Batas bandwidth/penyimpanan rilis tidak saya temukan sebagai "
                "angka resmi yang jelas — BELUM DIVERIFIKASI. Pakai fair use, "
                "hapus rilis lama. JANGAN taruh token di repo."
            ),
            "verified": False,
            "reset": "monthly_billing",
            "quota_signals": ["403", "429"],
        },
        {
            "id": "r2",
            "name": "Cloudflare R2",
            "akun": "arrowmichael17@gmail.com",
            "env": ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL"],
            "gratis": True,
            "limits": (
                "Tier gratis R2 yang sering dikutip: 10 GB-bulan penyimpanan, "
                "1 juta operasi Class A, 10 juta Class B per bulan, tanpa biaya egress. "
                "Angka ini BELUM DIVERIFIKASI di halaman resmi pada 12 Nov 2026. "
                "Perlu custom domain atau r2.dev public URL untuk IG."
            ),
            "verified": False,
            "reset": "monthly_billing",
            "quota_signals": ["403", "429", "SlowDown"],
        },
        {
            "id": "catbox",
            "name": "catbox.moe (anonim)",
            "akun": "— (tanpa kunci)",
            "env": [],
            "gratis": True,
            "always_available": True,
            "limits": (
                "Tanpa kunci, unggah anonim. Tidak ada SLA; file bisa dihapus. "
                "Batas ukuran (angka yang beredar ±200 MB) BELUM DIVERIFIKASI. "
                "Cek ToS sebelum pakai. Hanya sebagai cadangan terakhir."
            ),
            "verified": False,
            "reset": "unknown",
            "quota_signals": ["429", "403"],
        },
        {
            "id": "artifact",
            "name": "GitHub Actions Artifacts",
            "akun": "arrowmichael17@gmail.com",
            "env": ["GITHUB_TOKEN"],
            "gratis": True,
            "limits": (
                "Untuk antar-job di repo yang sama (bukan URL publik, jadi TIDAK "
                "bisa langsung untuk IG). GitHub Free: 500 MB storage (resmi, docs billing). "
                "Retention pendek (kita set 2 hari)."
            ),
            "verified": True,
            "reset": "monthly_billing",
            "quota_signals": ["403"],
        },
    ],
    "compute": [
        {
            "id": "github_actions_public",
            "name": "GitHub Actions (repo publik, standard runner)",
            "akun": "arrowmichael17@gmail.com",
            "env": [],
            "gratis": True,
            "limits": (
                "Standard GitHub-hosted runners (ubuntu-latest) GRATIS untuk repo "
                "publik, tanpa batas menit yang dipublikasikan, tunduk fair use "
                "(docs resmi GitHub, 2026). Storage artifact paket Free: 500 MB. "
                "Job timeout 6 jam. Repo HARUS privat jika khawatir log; tapi "
                "repo privat pakai jatah di bawah."
            ),
            "verified": True,
            "reset": "monthly_billing",
            "quota_signals": [],
        },
        {
            "id": "github_actions_private",
            "name": "GitHub Actions (repo privat, akun Free)",
            "akun": "arrowmichael17@gmail.com",
            "env": [],
            "gratis": True,
            "limits": (
                "Paket Free: $12 compute/bulan ≈ 2.000 menit di standard Linux 2-core "
                "(docs resmi + halaman pricing GitHub, 2026). Setelah jatah habis, "
                "job berhenti jika tidak ada metode pembayaran. Rekomendasi: repo "
                "publik untuk 5 video/hari agar tidak tertekan jatah menit; secret "
                "tetap tersembunyi di Actions."
            ),
            "verified": True,
            "reset": "monthly_billing",
            "quota_signals": [],
        },
        {
            "id": "github_actions_second_account",
            "name": "Cadangan: akun/repo GitHub kedua",
            "akun": "buat baru hanya jika diminta bro (bukan sekarang)",
            "env": [],
            "gratis": True,
            "limits": (
                "Jika fair use/menit akun pertama tertekan, workflow yang sama bisa "
                "dijalankan di repo (publik) akun Free lain. Perlu fork + secrets diisi ulang. "
                "Jangan umbar token antar-akun."
            ),
            "verified": True,
            "reset": "monthly_billing",
            "quota_signals": [],
        },
        {
            "id": "gitlab_ci",
            "name": "Cadangan: GitLab CI (paket Free)",
            "akun": "arrowmichael17@gmail.com",
            "env": [],
            "gratis": True,
            "limits": (
                "GitLab Free punya compute CI/CD bulanan. Angka yang sering dikutip "
                "(300–400 menit/bulan) BELUM DIVERIFIKASI per 12 Nov 2026 dan pernah "
                "berubah (kadang butuh kartu untuk verifikasi). File .gitlab-ci.yml "
                "disediakan sebagai cadangan, bukan jalur utama. Untuk 5 video/hari "
                "kemungkinan TIDAK cukup jika angka itu benar — hanya darurat pendek."
            ),
            "verified": False,
            "reset": "monthly_billing",
            "quota_signals": [],
        },
    ],
    "publish": [
        {
            "id": "fb_page_reels",
            "name": "Facebook Graph API video_reels (PAGE saja)",
            "akun": "radinalachmad@gmail.com",
            "env": ["FB_PAGE_ID", "FB_PAGE_TOKEN"],
            "gratis": True,
            "limits": (
                "30 Reels via API per 24 jam (moving window), jadwal 10 menit–29 hari "
                "(playbook, dari docs resmi Meta). TIDAK bisa publish ke profil pribadi, "
                "meski mode profesional."
            ),
            "verified": True,
            "reset": "rolling_24h",
            "quota_signals": ["4", "17", "32", "80004"],
        },
        {
            "id": "ig_reels",
            "name": "Instagram Content Publishing API (Creator/Business)",
            "akun": "radinalachmad@gmail.com / @achmad_radinal94",
            "env": ["IG_USER_ID", "IG_TOKEN"],
            "gratis": True,
            "limits": (
                "Guide resmi: 100 post via API / 24 jam. Halaman referensi "
                "content_publishing_limit masih menulis quota_total 50. Konflik ini "
                "BELUM DIVERIFIKASI untuk akun bro — cek endpoint. Tidak ada parameter "
                "jadwal; container kedaluwarsa 24 jam. Wajib video_url publik."
            ),
            "verified": False,
            "verified_note": "Keberadaan API dan absennya param jadwal: terverifikasi di playbook. Angka 100 vs 50: belum dipastikan di akun ini.",
            "reset": "rolling_24h",
            "quota_signals": ["4", "17", "32"],
        },
    ],
}

CHAINS: dict[str, list[str]] = {
    "llm": ["gemini", "groq", "github_models", "openrouter", "cloudflare", "huggingface", "template"],
    "tts": ["edge_tts", "gtts", "piper", "espeak"],
    "images": ["pexels", "pixabay", "unsplash", "openverse", "wikimedia", "local"],
    "hosting": ["github_release", "r2", "catbox"],
    "topics": [
        "google_trends_rss",
        "youtube_autocomplete",
        "youtube_api",
        "reddit_rss",
        "news_rss",
        "evergreen_bank",
    ],
}


def providers_for(category: str) -> list[dict]:
    return list(CATALOG.get(category, []))


def provider_meta(category: str, provider_id: str) -> dict | None:
    for p in CATALOG.get(category, []):
        if p["id"] == provider_id:
            return p
    return None
