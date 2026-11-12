# Catatan uji sampel (koreksi)

Tanggal: 12 November 2026 (WITA)

Sumber: umpan balik uji putar `samples/sample_reel.mp4` (versi awal, ±64,5 detik).
Putaran ini **tidak** merender ulang sampel; file itu tetap artefak uji pertama.

## Temuan uji awal

1. **Running text / caption**
   - Kadang terlalu cepat.
   - Kata atau kalimat berulang bolak-balik, lalu meloncat ke bagian lain.
   - Belum seimbang dengan voice-over.

   Ini bukan hanya efek “pertama kali pembuatan”. Di kode versi awal ada dua penyebab yang jelas:

   - `current_word_index` mengembalikan indeks 0 jika waktu jatuh di celah antar peristiwa `WordBoundary` (jeda antar kata). Caption meloncat kembali ke kata pertama, lalu maju lagi — itu yang terasa berulang bolak-balik.
   - `draw_karaoke` memakai jendela geser di sekitar kata aktif (kira-kira −4 sampai +8 kata). Kata muncul, lalu hilang saat jendela bergeser, jadi teks tidak stabil di layar.

2. **Durasi**
   - 64 detik terasa terlalu lama; penonton cepat bosan.
   - Target baru: **30–40 detik** per Reels, batas keras **~45 detik**.
   - Anggaran naskah: **~75–100 kata** bahasa Indonesia, hook kuat di 2 detik pertama.

## Koreksi yang diterapkan di kode

- Timing caption diambil dari batas kata TTS nyata (peristiwa WordBoundary edge-tts). Mesin TTS cadangan tanpa batas kata memakai taksiran proporsional suku kata/karakter plus deteksi sunyi pada audio.
- Caption ditampilkan dalam *chunk* stabil 2–4 kata (atau satu baris pendek), minimal ~0,6 detik di layar, maju monotik, tanpa tumpang tindih, tanpa mengulang kata sebelumnya. Kata yang sedang diucapkan boleh di-highlight di dalam chunk yang sama.
- Renderer dan QC memotong/menolak video di atas 45 detik. Penulis naskah memaksa anggaran kata.
- Gerbang QC pra-publish menolak tayang jika cek timing caption atau cek durasi gagal.

Lihat `tests/test_captions.py` untuk uji monotik / tanpa tumpang tindih / tanpa duplikat, dan `qc.pre_publish_gate`.
