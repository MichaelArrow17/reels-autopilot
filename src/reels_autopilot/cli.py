"""Antarmuka baris perintah: reels-autopilot <perintah>."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from reels_autopilot import __version__
from reels_autopilot.config import SLOTS, get_settings
from reels_autopilot.pipeline import Pipeline
from reels_autopilot.providers.catalog import CHAINS
from reels_autopilot.providers.router import ProviderRouter
from reels_autopilot.qc import inspect, report_text
from reels_autopilot.state import today_wita
from reels_autopilot.telegram_bot import TelegramBot


def _setup_log(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reels-autopilot",
        description="Pipeline Reels otonom (gratis) untuk Po Chai / Kreator AI",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--version", action="version", version=f"reels-autopilot {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scout", help="Kumpulkan & skor topik, kirim shortlist ke Telegram")

    p_prod = sub.add_parser("produce", help="Tulis naskah, TTS, render, QC, preview")
    p_prod.add_argument("--date", default=None, help="YYYY-MM-DD (default: hari ini WITA)")
    p_prod.add_argument("--limit", type=int, default=None)

    p_pub = sub.add_parser("publish", help="Publish 1 slot (default DRY_RUN)")
    p_pub.add_argument("--slot", type=int, required=True, choices=[s["id"] for s in SLOTS])
    p_pub.add_argument("--date", default=None)

    p_h = sub.add_parser("handoff", help="Kirim paket share FB ke Telegram (tanpa publish ulang)")
    p_h.add_argument("--slot", type=int, required=True, choices=[s["id"] for s in SLOTS])
    p_h.add_argument("--date", default=None)
    p_h.add_argument("--mp4", default=None, help="Path MP4 jika tidak ada di job dir")
    p_h.add_argument("--permalink", default=None)
    p_h.add_argument("--chat-id", default=None)

    sub.add_parser("poll", help="Ambil perintah Telegram (getUpdates)")

    p_once = sub.add_parser("run-once", help="Satu video end-to-end (DRY_RUN)")
    p_once.add_argument("--judul", default=None)
    p_once.add_argument("--hook", default=None)

    p_sample = sub.add_parser("sample", help="Render sampel resmi ke samples/")
    p_sample.add_argument("--out", default=None)

    p_ss = sub.add_parser("sample-styles", help="Render sampel uji gaya visual, opsional kirim Telegram")
    p_ss.add_argument("--out-dir", default=None, help="Folder output (default: samples/)")
    p_ss.add_argument("--send", action="store_true", help="Kirim ke Telegram sebagai SAMPEL UJI (bukan ACC)")
    p_ss.add_argument("--only", default=None, choices=["penjelas", "cerita", "kolase"], help="Render satu gaya saja")

    p_qc = sub.add_parser("qc", help="Periksa sebuah MP4")
    p_qc.add_argument("path")

    sub.add_parser("refresh-ig-token", help="Refresh long-lived IG token dan tulis ke GitHub Secret")
    sub.add_parser("providers", help="Tampilkan rantai failover, batas, dan status cooldown")
    sub.add_parser("status", help="Status antrian hari ini")

    args = parser.parse_args(argv)
    _setup_log(args.verbose)
    settings = get_settings()
    pipe = Pipeline(settings)

    if args.cmd == "scout":
        result = pipe.scout_and_notify()
        print(json.dumps({k: result[k] for k in result if k != "ditolak"} | {
            "ditolak_count": len(result.get("ditolak") or []),
            "shortlist_count": len(result.get("shortlist") or []),
        }, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.cmd == "produce":
        out = pipe.produce_day(args.date, limit=args.limit)
        print(json.dumps([{"id": v.get("id"), "slot": v.get("slot"), "status": v.get("status"),
                           "mp4": v.get("mp4"), "qc_ok": v.get("qc_ok")} for v in out],
                         ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "handoff":
        from pathlib import Path as _P
        date = args.date or today_wita(settings)
        v = pipe.state.video_by_slot(args.slot, date)
        if not v:
            print(json.dumps({"ok": False, "reason": "no_video", "slot": args.slot, "date": date}, ensure_ascii=False))
            return 1
        mp4 = _P(args.mp4) if args.mp4 else _P(v.get("mp4") or "")
        permalink = args.permalink or ((v.get("publish") or {}).get("ig") or {}).get("permalink")
        public_url = ((v.get("publish") or {}).get("host") or {}).get("url")
        res = pipe.tg.send_fb_handoff(
            mp4=mp4 if mp4.exists() else None,
            caption=v.get("caption") or "",
            permalink=permalink,
            public_url=public_url,
            chat_id=args.chat_id,
        )
        # jangan cetak token; parts boleh ada error text
        safe = {"ok": res.get("ok"), "parts": []}
        for part in res.get("parts") or []:
            safe["parts"].append({
                "ok": part.get("ok"),
                "reason": part.get("reason"),
                "error": part.get("error"),
                "message_id": ((part.get("result") or {}).get("message_id") if isinstance(part.get("result"), dict) else None),
            })
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    if args.cmd == "publish":
        res = pipe.publish_slot(args.slot, args.date)
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        skip_ok = {
            "rejected",
            "skipped",
            "published",
            "paused",
            "no_video",
            "meta_secrets_missing",
            "ig_secrets_missing",
        }
        if res.get("ok") or res.get("reason") in skip_ok:
            if not res.get("ok"):
                print(f"Publish dilewati: {res.get('reason')}")
            return 0
        return 1

    if args.cmd == "poll":
        acts = pipe.tg.poll()
        print(json.dumps(acts, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "run-once":
        topic = None
        if args.judul:
            topic = {"judul": args.judul, "hook": args.hook or args.judul}
        res = pipe.run_once(topic=topic)
        print(json.dumps({"mp4": res["video"].get("mp4"), "status": res["video"].get("status"),
                          "qc": res["video"].get("qc"), "publish": res["publish"]},
                         ensure_ascii=False, indent=2, default=str))
        return 0 if res["video"].get("qc_ok", True) else 1

    if args.cmd == "sample":
        dest = Path(args.out) if args.out else None
        res = pipe.sample(dest)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        qc_ok = (res.get("qc") or {}).get("ok")
        return 0 if qc_ok else 2

    if args.cmd == "sample-styles":
        from reels_autopilot.uji_samples import render_uji_samples, send_uji_samples
        dest = Path(args.out_dir) if args.out_dir else (settings.samples_dir)
        res = render_uji_samples(dest, settings=settings, only=args.only)
        # jangan cetak teks panjang berlebih; ringkas
        summary = {}
        for k, v in res.items():
            summary[k] = {
                "mp4": v.get("mp4"),
                "duration": v.get("duration"),
                "render_seconds": v.get("render_seconds"),
                "voice": v.get("voice"),
                "verify_ok": (v.get("verify") or {}).get("ok"),
                "issues": (v.get("verify") or {}).get("issues"),
            }
        if args.send:
            sent = send_uji_samples(res, settings=settings)
            summary["telegram"] = sent
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        ok = all((res[k].get("verify") or {}).get("ok") for k in res if isinstance(res.get(k), dict) and "verify" in (res[k] or {}))
        return 0 if ok else 2

    if args.cmd == "qc":
        q = inspect(args.path)
        print(report_text(q))
        print(json.dumps(q.to_dict(), ensure_ascii=False, indent=2))
        return 0 if q.ok else 2

    if args.cmd == "refresh-ig-token":
        from reels_autopilot.ig_token import run as refresh_ig
        res = refresh_ig(settings)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        # skip karena secret belum ada = sukses bersih (workflow bulanan tidak merah)
        if res.get("ok") or res.get("reason") in {"ig_secrets_missing", "gh_pat_missing", "repo_missing"}:
            return 0
        return 1

    if args.cmd == "providers":
        router = ProviderRouter(settings)
        report = router.report()
        # tambahkan info chain + catalog limits
        print(f"reels-autopilot {__version__}  DRY_RUN={settings.dry_run}  mode={settings.approval_mode}")
        print(f"Rantai: {json.dumps(CHAINS, ensure_ascii=False)}")
        print()
        for cat, rows in report.items():
            print(f"== {cat} ==")
            for r in rows:
                flag = "COOLDOWN" if r["cooling"] else ("KUOTA" if r["quota_exhausted"] else "siap")
                ver = "terverifikasi" if r["verified_limits"] else "BELUM DIVERIFIKASI"
                print(f"  - {r['id']:16} [{flag:8}] {r['name']}  ({ver})")
                if r["cooling"]:
                    print(f"      cooldown sisa ~{r['cooldown_remaining_min']} menit, sampai {r['cooldown_until']}")
                if r["last_error"]:
                    print(f"      error terakhir: {r['last_error'][:120]}")
                print(f"      sukses={r['success_count']} gagal={r['failure_count']}")
                # batas singkat
                lim = (r.get("limits") or "").replace("\n", " ")
                print(f"      batas: {lim[:200]}{'…' if len(lim)>200 else ''}")
            print()
        return 0

    if args.cmd == "status":
        print(TelegramBot(settings, pipe.state).status_text())
        print(f"DRY_RUN={settings.dry_run}  tanggal={today_wita(settings)} WITA")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
