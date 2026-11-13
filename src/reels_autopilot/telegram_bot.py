"""Bot Telegram: shortlist, preview, veto/approve, status, pause.

Tidak butuh server 24 jam — di-poll oleh GitHub Actions (getUpdates) pada
jendela approval dan di awal setiap job produce/publish.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from reels_autopilot.config import Settings, get_settings
from reels_autopilot.state import State, today_wita

log = logging.getLogger("reels.tg")
API = "https://api.telegram.org/bot{token}/{method}"
TG_VIDEO_MAX_BYTES = 50 * 1024 * 1024
FB_HANDOFF_VIDEO_CAPTION = "Siap share ke FB Po Chai"
FB_HANDOFF_HOWTO = (
    "Share ke FB Po Chai: tahan video ini → Bagikan → Facebook → Reels, tempel caption, Bagikan."
)
TG_VIDEO_CAPTION_MAX = 1024


def html_escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def preview_message_html(video: dict, *, already_approved: bool | None = None, approval_mode: str = "required") -> str:
    """Satu pesan preview: header + caption final (blok salin) + cara share FB + ACC/TOLAK."""
    slot = video.get("slot")
    judul = html_escape(str(video.get("judul") or ""))
    jam = html_escape(str(video.get("slot_label") or ""))
    cap = html_escape((video.get("caption") or "").strip() or "(caption kosong)")
    if already_approved is None:
        already_approved = video.get("status") == "approved"
    header = f"Preview slot {slot} — {judul}"
    if already_approved:
        status = f"Sudah ACC, tayang jam {jam} WITA."
        gate = (
            f"Balas TOLAK {slot} untuk batal. ACC sudah tercatat, tidak perlu ACC lagi."
        )
    elif approval_mode == "required":
        status = f"Jam tayang: {jam} WITA."
        gate = (
            f"Balas OK atau ACC {slot} supaya boleh tayang di IG. "
            f"Tanpa ACC, slot ini tidak dipublish. TOLAK {slot} untuk batal."
        )
    else:
        status = f"Jam tayang: {jam} WITA."
        gate = (
            f"Balas TOLAK {slot} untuk batal, atau biarkan untuk tayang "
            f"(mode {html_escape(approval_mode)})."
        )
    return "\n".join(
        [
            header,
            status,
            "",
            "Caption siap tempel ke IG dan FB Po Chai (ketuk blok, lalu salin):",
            "",
            f"<pre><code>{cap}</code></pre>",
            "",
            html_escape(FB_HANDOFF_HOWTO),
            "",
            gate,
        ]
    )


def published_notice_text(video: dict, permalink: str | None = None) -> str:
    """Setelah tayang: catatan singkat + tautan IG, tanpa file atau caption ulang."""
    slot = video.get("slot")
    jam = video.get("slot_label") or ""
    judul = video.get("judul") or ""
    lines = [f"Sudah tayang slot {slot} ({jam} WITA) — {judul}"]
    if permalink:
        lines.append(str(permalink))
    return "\n".join(lines)


def fb_handoff_text(caption: str, permalink: str | None = None) -> str:
    """Pesan 2: caption siap salin (blok monospace) + cara share + permalink IG."""
    body = html_escape((caption or "").strip() or "(caption kosong)")
    lines = [
        "Caption siap tempel ke FB Po Chai (ketuk blok di bawah, lalu salin):",
        "",
        f"<pre><code>{body}</code></pre>",
        "",
        html_escape(FB_HANDOFF_HOWTO),
    ]
    if permalink:
        lines.extend(["", html_escape(str(permalink))])
    return "\n".join(lines)


class TelegramBot:
    def __init__(self, settings: Settings | None = None, state: State | None = None):
        self.settings = settings or get_settings()
        self.state = state or State(self.settings)

    @property
    def configured(self) -> bool:
        return bool(self.settings.telegram_bot_token)

    @property
    def chat_id(self) -> str:
        return (
            self.settings.telegram_chat_id
            or (self.state.data.get("telegram") or {}).get("chat_id")
            or ""
        )

    def _call(self, method: str, **kwargs) -> dict:
        # DRY_RUN hanya menahan publish Meta. Notifikasi approval tetap dikirim
        # jika bot sudah dikonfigurasi, supaya preview sampai ke Telegram.
        if not self.configured:
            dest = self.settings.dry_run_dir / f"telegram_{method}_{datetime.now().strftime('%H%M%S%f')}.json"
            dest.write_text(json.dumps({"method": method, **_safe(kwargs)}, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info("Telegram belum dikonfigurasi; %s ditulis ke %s", method, dest)
            return {"ok": False, "reason": "not_configured", "path": str(dest)}
        url = API.format(token=self.settings.telegram_bot_token, method=method)
        files = kwargs.pop("files", None)
        if files:
            r = requests.post(url, data=kwargs, files=files, timeout=60)
        else:
            r = requests.post(url, json=kwargs, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data}")
        return data

    def send(self, text: str, *, chat_id: str | None = None, parse_mode: str | None = None) -> dict:
        cid = chat_id or self.chat_id
        if not cid:
            log.warning("TELEGRAM_CHAT_ID kosong, pesan tidak terkirim")
            return {"ok": False, "reason": "no chat_id"}
        payload: dict[str, Any] = {"chat_id": cid, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return self._call("sendMessage", **payload)

    def send_video(
        self,
        mp4: Path,
        caption: str = "",
        *,
        chat_id: str | None = None,
        supports_streaming: bool = True,
        parse_mode: str | None = None,
    ) -> dict:
        cid = chat_id or self.chat_id
        extra: dict[str, Any] = {}
        if supports_streaming:
            extra["supports_streaming"] = "true"
        if parse_mode:
            extra["parse_mode"] = parse_mode
        if not self.configured:
            return self._call(
                "sendVideo",
                chat_id=cid or "DRY_RUN",
                caption=caption,
                path=str(mp4),
                **extra,
            )
        if not cid:
            log.warning("TELEGRAM_CHAT_ID kosong, video tidak terkirim")
            return {"ok": False, "reason": "no chat_id"}
        text = caption or ""
        if len(text) > TG_VIDEO_CAPTION_MAX:
            # jangan potong blok HTML/caption final di tengah jalan
            log.error("Caption video Telegram %s karakter > %s", len(text), TG_VIDEO_CAPTION_MAX)
            return {"ok": False, "reason": "caption_too_long", "length": len(text)}
        with Path(mp4).open("rb") as f:
            return self._call(
                "sendVideo",
                chat_id=cid,
                caption=text,
                files={"video": (Path(mp4).name, f, "video/mp4")},
                **extra,
            )

    def send_document(self, path: Path, caption: str = "", *, chat_id: str | None = None) -> dict:
        cid = chat_id or self.chat_id
        if not self.configured:
            return self._call("sendDocument", chat_id=cid or "DRY_RUN", caption=caption, path=str(path))
        if not cid:
            log.warning("TELEGRAM_CHAT_ID kosong, dokumen tidak terkirim")
            return {"ok": False, "reason": "no chat_id"}
        with Path(path).open("rb") as f:
            return self._call(
                "sendDocument",
                chat_id=cid,
                caption=(caption or "")[:1024],
                files={"document": (Path(path).name, f, "application/octet-stream")},
            )

    def _try_send(self, label: str, fn) -> dict:
        """Kirim, retry sekali jika exception; tidak melempar ke pemanggil."""
        try:
            return fn()
        except Exception as e:
            log.warning("Telegram %s gagal, coba sekali lagi: %s", label, e)
            try:
                return fn()
            except Exception as e2:
                log.error("Telegram %s gagal setelah retry: %s", label, e2)
                return {
                    "ok": False,
                    "reason": "telegram_send_failed",
                    "error": f"{type(e2).__name__}: {e2}"[:400],
                }

    def send_fb_handoff(
        self,
        *,
        mp4: Path | str | None,
        caption: str,
        permalink: str | None = None,
        public_url: str | None = None,
        chat_id: str | None = None,
    ) -> dict:
        """Paket 2 pesan setelah IG tayang: video + caption/cara share. Gagal Telegram tidak boleh meledak."""
        cid = chat_id or self.chat_id
        parts: list[dict] = []
        video_caption = FB_HANDOFF_VIDEO_CAPTION
        path = Path(mp4) if mp4 else None
        size = path.stat().st_size if path and path.exists() else 0

        def send_media() -> dict:
            if path and path.exists() and size <= TG_VIDEO_MAX_BYTES:
                return self.send_video(path, video_caption, chat_id=cid, supports_streaming=True)
            if path and path.exists() and size <= TG_VIDEO_MAX_BYTES * 2:
                # di atas 50 MB: coba dokumen; jika API menolak, pemanggil retry/tautan
                return self.send_document(path, video_caption, chat_id=cid)
            if public_url:
                return self.send(f"{video_caption}\n{public_url}", chat_id=cid)
            if path and path.exists():
                return self.send(
                    f"{video_caption}\nFile terlalu besar untuk Telegram ({size} byte)."
                    + (f"\n{public_url}" if public_url else ""),
                    chat_id=cid,
                )
            if public_url:
                return self.send(f"{video_caption}\n{public_url}", chat_id=cid)
            return self.send(f"{video_caption}\n(Video tidak tersedia di runner.)", chat_id=cid)

        media = self._try_send("handoff_video", send_media)
        # Jika sendVideo/document gagal, jatuhkan ke tautan rilis jika ada.
        if not media.get("ok") and public_url:
            media = self._try_send(
                "handoff_video_link",
                lambda: self.send(f"{video_caption}\n{public_url}", chat_id=cid),
            )
        parts.append(media)

        text = fb_handoff_text(caption, permalink)

        def send_caption() -> dict:
            return self.send(text, chat_id=cid, parse_mode="HTML")

        cap_res = self._try_send("handoff_caption", send_caption)
        if not cap_res.get("ok"):
            # fallback tanpa HTML jika parse_mode ditolak
            plain = (
                f"Caption siap tempel ke FB Po Chai:\n\n{caption}\n\n"
                f"{FB_HANDOFF_HOWTO}"
                + (f"\n\n{permalink}" if permalink else "")
            )
            cap_res = self._try_send(
                "handoff_caption_plain",
                lambda: self.send(plain, chat_id=cid),
            )
        parts.append(cap_res)
        ok = all(p.get("ok") for p in parts)
        return {"ok": ok, "parts": parts}

    def send_shortlist(self, result: dict) -> dict:
        tanggal = result.get("tanggal") or today_wita(self.settings)
        lines = [f"Pagi bro, shortlist {tanggal} (WITA):"]
        for i, s in enumerate(result.get("shortlist") or [], 1):
            skor = s.get("skor_total", "?")
            tipe = s.get("tipe", "")
            hook = s.get("hook") or s.get("judul")
            lines.append(f"{i}) {hook} (skor {skor}, {tipe})")
        mode = self.settings.approval_mode
        if mode == "veto":
            lines.append(
                "\nMode veto: otomatis lanjut kecuali kamu balas TOLAK 2 (atau TOLAK 2 4). "
                "/status untuk antrian, /pause untuk hentikan sisa hari ini."
            )
        elif mode == "required":
            lines.append("\nMode wajib setujui: balas OK atau 1 2 3 4 5. /skip untuk lewat hari ini.")
        else:
            lines.append("\nMode auto: ini pemberitahuan saja. /pause kalau mau ditahan.")
        if result.get("filter_provider"):
            lines.append(f"\nFilter: {result['filter_provider']}")
        return self.send("\n".join(lines))

    def send_preview(
        self,
        video: dict,
        mp4: Path | None = None,
        *,
        already_approved: bool | None = None,
    ) -> dict:
        text = preview_message_html(
            video,
            already_approved=already_approved,
            approval_mode=self.settings.approval_mode,
        )
        if mp4 and Path(mp4).exists() and Path(mp4).stat().st_size < 49_000_000:
            return self.send_video(Path(mp4), text, parse_mode="HTML")
        return self.send(text, parse_mode="HTML")

    def send_published_notice(
        self,
        video: dict,
        permalink: str | None = None,
        *,
        chat_id: str | None = None,
    ) -> dict:
        return self.send(published_notice_text(video, permalink), chat_id=chat_id)

    def poll(self) -> list[dict]:
        """Ambil update baru, proses perintah, kembalikan aksi yang terjadi."""
        actions: list[dict] = []
        if not self.configured:
            log.info("Telegram tidak dikonfigurasi; poll dilewati")
            return actions
        offset = self.state.telegram_offset()
        r = requests.get(
            API.format(token=self.settings.telegram_bot_token, method="getUpdates"),
            params={"offset": offset + 1, "timeout": 0, "allowed_updates": json.dumps(["message"])},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"getUpdates: {data}")
        for upd in data.get("result") or []:
            uid = int(upd.get("update_id") or 0)
            self.state.set_telegram_offset(max(self.state.telegram_offset(), uid))
            msg = upd.get("message") or upd.get("edited_message") or {}
            text = (msg.get("text") or "").strip()
            chat = (msg.get("chat") or {}).get("id")
            if chat:
                self.state.set_chat_id(chat)
            if not text:
                continue
            act = self._handle(text, str(chat) if chat else "")
            if act:
                actions.append(act)
        return actions

    def _handle(self, text: str, chat_id: str) -> dict | None:
        t = text.strip()
        low = t.lower()
        date = today_wita(self.settings)

        def reply(msg: str) -> None:
            self.send(msg, chat_id=chat_id)

        if low in {"/start", "start"}:
            reply("Bot Po Chai siap, bro. /status · /pause · /resume · TOLAK 2 · OK / ACC 1")
            return {"action": "start"}
        if low in {"/status", "status"}:
            reply(self.status_text(date))
            return {"action": "status"}
        if low in {"/pause", "pause"}:
            self.state.pause()
            reply("Ditahan. Sisa slot hari ini tidak akan dipublish sampai /resume.")
            return {"action": "pause"}
        if low in {"/resume", "resume"}:
            self.state.resume()
            reply("Dilanjut lagi.")
            return {"action": "resume"}
        if low in {"/skip", "skip"}:
            for v in self.state.videos(date):
                if v.get("status") not in {"published", "rejected"}:
                    v["status"] = "skipped"
                    self.state.upsert_video(v, date)
            reply("Sisa video hari ini dilewati.")
            return {"action": "skip"}
        m = re.match(r"^/?tolak\s+([\d\s,]+)$", low)
        if m:
            slots = [int(x) for x in re.findall(r"\d+", m.group(1))]
            for sl in slots:
                v = self.state.video_by_slot(sl, date)
                if v:
                    v["status"] = "rejected"
                    self.state.upsert_video(v, date)
            reply(f"Ditolak: slot {slots}. Tidak akan tayang.")
            return {"action": "reject", "slots": slots}
        m = re.match(r"^/?(ok|ya|approve|setuju|acc)\s*([\d\s,]*)$", low)
        if m:
            nums = [int(x) for x in re.findall(r"\d+", m.group(2) or "")]
            vids = self.state.videos(date)
            if not nums:
                for v in vids:
                    if v.get("status") in {"pending_approval", "rendered", "pending"}:
                        v["status"] = "approved"
                        self.state.upsert_video(v, date)
                reply("Semua yang menunggu disetujui.")
                return {"action": "approve_all"}
            for sl in nums:
                v = self.state.video_by_slot(sl, date)
                if v:
                    v["status"] = "approved"
                    self.state.upsert_video(v, date)
            reply(f"Disetujui: slot {nums}.")
            return {"action": "approve", "slots": nums}
        # angka saja: di mode required = pilih topik
        if re.fullmatch(r"[\d\s,]+", t):
            nums = [int(x) for x in re.findall(r"\d+", t)]
            day = self.state.day(date)
            short = day.get("shortlist") or []
            if short and self.settings.approval_mode == "required":
                chosen = []
                for n in nums:
                    if 1 <= n <= len(short):
                        chosen.append(short[n - 1])
                day["selected"] = chosen
                self.state.save()
                reply(f"Dipilih {len(chosen)} topik. Produksi menyusul.")
                return {"action": "select", "n": nums}
        return None

    def status_text(self, date: str | None = None) -> str:
        date = date or today_wita(self.settings)
        day = self.state.day(date)
        paused = "YA (ditahan)" if self.state.is_paused() else "tidak"
        lines = [
            f"Status {date} WITA — jeda: {paused}",
            f"Mode: {self.settings.approval_mode}  DRY_RUN={self.settings.dry_run}",
            f"Shortlist: {len(day.get('shortlist') or [])}",
        ]
        for v in day.get("videos") or []:
            lines.append(
                f"  slot {v.get('slot')}: {v.get('status')} — {v.get('judul', '')[:50]}"
            )
        if not (day.get("videos")):
            lines.append("  (belum ada video hari ini)")
        return "\n".join(lines)


def _safe(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if k in {"token", "files"}:
            out[k] = "***"
        else:
            out[k] = v if not isinstance(v, (bytes, bytearray)) else f"<{len(v)} bytes>"
    return out
