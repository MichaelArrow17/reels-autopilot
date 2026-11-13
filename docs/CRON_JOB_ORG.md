# Pemicu cadangan cron-job.org

GitHub Actions `on.schedule` kadang telat atau tidak terpicu, terutama di repo baru.
cron-job.org (akun arrowmichael17, paket gratis) memanggil `workflow_dispatch` di
jam yang sama. Dua pemicu boleh jalan bersamaan: job menunggu antrean concurrency,
lalu membaca `data/state.json` terbaru dan melewati scout/produce/publish yang
sudah dikerjakan.

## Token (nama saja, tanpa nilai)

Jangan tempel PAT yang sudah dipakai untuk `GH_PAT` / `.secrets/github.env`.
PAT itu longgar (bisa baca Actions secrets dan isi repo).

Pemicu cron-job.org memakai **PAT fine-grained terpisah**:

- Nama: `CRON_DISPATCH_PAT`
- Resource owner: `MichaelArrow17`
- Repository access: hanya `MichaelArrow17/reels-autopilot`
- Permissions: **Actions: Read and write** (Metadata: Read ikut otomatis)
- **Kedaluwarsa: 11 Februari 2027** — perpanjang sebelum tanggal itu
- Disimpan di `.secrets/cron_dispatch.env` (gitignored) dan pengelola kata sandi
- Nilai token tidak dicatat di repo ini

API cron-job.org memakai Bearer `CRONJOB_API_KEY` (nama saja), file yang sama.
Kunci itu punya batas harian dan sekitar 1 permintaan/detik; jangan di-commit.

Buat PAT cadangan baru di: https://github.com/settings/personal-access-tokens/new

## Pengaturan umum tiap job (cron-job.org)

- Timezone: **Asia/Makassar** (bukan Asia/Jakarta, itu UTC+7)
- URL, method, header, dan body di bawah; ganti `<TOKEN>` dengan PAT cadangan
- Header:
  - `Authorization: Bearer <TOKEN>`
  - `Accept: application/vnd.github+json`
  - `X-GitHub-Api-Version: 2022-11-28`
  - `Content-Type: application/json`
  - `User-Agent: cron-job.org-reels-autopilot`
- Notification: email jika gagal (HTTP bukan 2xx). Dispatch sukses = **204**.

Basis URL:

`https://api.github.com/repos/MichaelArrow17/reels-autopilot/actions/workflows/<FILE>/dispatches`

`ref` selalu `main`.

## Jadwal (WITA)

| Job | WITA | File workflow | Body JSON | Catatan |
|---|---|---|---|---|
| scout | 06:00 setiap hari | `scout.yml` | `{"ref":"main"}` | Tidak ada input |
| produce | 06:30 setiap hari | `produce.yml` | `{"ref":"main"}` | `limit` opsional, jangan diisi |
| poll Telegram | 06:00, 06:20, 06:40, 07:00, 07:20, 07:40, 08:00, 08:20, 08:40 | `poll.yml` | `{"ref":"main"}` | ACC di luar jendela ini tetap dibaca di awal job publish |
| publish slot 1 | 07:30 setiap hari | `publish.yml` | `{"ref":"main","inputs":{"slot":"1"}}` | Selalu kirim `slot` |
| publish slot 2 | 12:00 setiap hari | `publish.yml` | `{"ref":"main","inputs":{"slot":"2"}}` | |
| publish slot 3 | 17:00 setiap hari | `publish.yml` | `{"ref":"main","inputs":{"slot":"3"}}` | |
| publish slot 4 | 19:00 setiap hari | `publish.yml` | `{"ref":"main","inputs":{"slot":"4"}}` | |
| publish slot 5 | 21:00 setiap hari | `publish.yml` | `{"ref":"main","inputs":{"slot":"5"}}` | |
| health check token IG | Senin 09:00 | `refresh-ig-token.yml` | `{"ref":"main"}` | Token SYSTEM_USER yang tidak kedaluwarsa dilewati |
| refresh token IG | tanggal 1, 08:00 | `refresh-ig-token.yml` | `{"ref":"main"}` | Sama seperti health check; idempoten untuk token tanpa expiry |

Jika input `slot` kosong, workflow mendeteksi dari jam WITA (atau dari cron GitHub
jika event-nya `schedule`). Tetap kirim `slot` di cron-job.org agar telat beberapa
menit tidak salah pilih.

Jangan isi `dry_run` (supaya memakai variabel repo) dan jangan isi
`artifact_run_id` kecuali memulihkan artifak produce tertentu. Jika kosong,
workflow memakai artifak run produce sukses terbaru (yang ACC-mu lihat),
bukan merender ulang.

## Kuota gratis cron-job.org

Paket gratis membatasi jumlah job dan interval (biasanya minimal 1 menit, dan
jumlah cron terbatas — cek batas akun saat mendaftar). 5 publish + scout +
produce + 1 health + 1 monthly + poll (bisa 1 job dengan banyak jam, atau
beberapa job) harus muat; jika kuota sempit, utamakan 5 slot publish + scout +
produce, karena publish sudah mem-poll Telegram.

## GitHub schedule (UTC) yang tetap dipertahankan

Ini cadangan timbal-balik, jangan dihapus:

- scout `0 22 * * *`
- produce `30 22 * * *`
- poll `0,20,40 22-23 * * *` dan `0,20,40 0 * * *`
- publish `30 23 * * *`, `0 4 * * *`, `0 9 * * *`, `0 11 * * *`, `0 13 * * *`
- refresh `0 1 * * 1` (Senin 09:00 WITA) dan `0 0 1 * *` (tgl 1 08:00 WITA)

## Job yang sudah dibuat (akun arrowmichael17)

Folder `reels-autopilot` (`folderId` 68266). Timezone `Asia/Makassar`, POST, notifikasi gagal aktif.
Uji hidup: job poll memicu `workflow_dispatch` poll-telegram 13 Nov 2026 08:00:30 WITA, sukses
(https://github.com/MichaelArrow17/reels-autopilot/actions/runs/43333528856).

| Job id | Judul | Jadwal WITA |
|---|---|---|
| 8853723 | reels poll Telegram | 06:00, 06:20, 06:40, 07:00, 07:20, 07:40, 08:00, 08:20, 08:40 setiap hari |
| 8853725 | reels scout 06:00 | 06:00 setiap hari |
| 8853726 | reels produce 06:30 | 06:30 setiap hari |
| 8853728 | reels publish slot 1 07:30 | 07:30 setiap hari |
| 8853730 | reels publish slot 2 12:00 | 12:00 setiap hari |
| 8853731 | reels publish slot 3 17:00 | 17:00 setiap hari |
| 8853734 | reels publish slot 4 19:00 | 19:00 setiap hari |
| 8853735 | reels publish slot 5 21:00 | 21:00 setiap hari |
| 8853737 | reels IG token health Senin 09:00 | Senin 09:00 |
| 8853740 | reels IG token monthly tgl 1 08:00 | tanggal 1, 08:00 |
