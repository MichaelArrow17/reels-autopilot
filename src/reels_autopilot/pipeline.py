"""Orkestrasi end-to-end: scout → naskah → TTS → render → QC → preview → publish."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from reels_autopilot.captions import chunk_captions
from reels_autopilot.config import HARD_MAX_DURATION, SLOTS, Settings, get_settings
from reels_autopilot.providers.images import ImageClient
from reels_autopilot.providers.router import ProviderRouter
from reels_autopilot.providers.tts import TTSClient, Word
from reels_autopilot.publisher import Publisher
from reels_autopilot.qc import QCRejected, inspect, pre_publish_gate, report_text
from reels_autopilot.renderer import render_video
from reels_autopilot.script_writer import ScriptWriter, _word_count, fallback_script, trim_to_word_budget
from reels_autopilot.state import State, today_wita
from reels_autopilot.telegram_bot import TelegramBot
from reels_autopilot.topic_scout import TopicScout

log = logging.getLogger("reels.pipeline")


def _slot_label(slot: dict) -> str:
    return f"{slot['hour']:02d}:{slot['minute']:02d}"


def _job_dir(settings: Settings, date: str, slot: int) -> Path:
    p = settings.jobs_dir / date / f"slot{slot}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_job_words(video: dict) -> list[Word] | None:
    script_path = video.get("script_path")
    candidates = []
    if script_path:
        candidates.append(Path(script_path).with_name("words.json"))
    mp4 = video.get("mp4")
    if mp4:
        candidates.append(Path(mp4).with_name("words.json"))
    for path in candidates:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return [
                Word(word=d["word"], start=float(d["start"]), duration=float(d["duration"]))
                for d in data
            ]
    return None


class Pipeline:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.state = State(self.settings)
        self.router = ProviderRouter(self.settings)
        self.scout = TopicScout(self.settings, self.state)
        self.writer = ScriptWriter(self.settings, self.router)
        self.tts = TTSClient(self.settings, self.router)
        self.images = ImageClient(self.settings, self.router)
        self.publisher = Publisher(self.settings)
        self.tg = TelegramBot(self.settings, self.state)

    def scout_and_notify(self) -> dict:
        result = self.scout.run(use_llm=True)
        self.tg.send_shortlist(result)
        # siapkan antrian video dari shortlist (status pending)
        date = result["tanggal"]
        existing = {v.get("slot"): v for v in self.state.videos(date)}
        short = result.get("shortlist") or []
        if self.settings.approval_mode == "required":
            # tunggu pilihan; jika sudah ada selected, pakai itu
            short = self.state.day(date).get("selected") or short
        for i, slot in enumerate(SLOTS[: self.settings.daily_quota]):
            if slot["id"] in existing:
                continue
            topic = short[i] if i < len(short) else None
            if not topic:
                continue
            vid = {
                "id": f"{date}-s{slot['id']}-{uuid.uuid4().hex[:6]}",
                "slot": slot["id"],
                "slot_label": _slot_label(slot),
                "judul": topic.get("judul"),
                "hook": topic.get("hook"),
                "topic": topic,
                "status": "pending",
                "created_at": datetime.now(self.settings.tz).isoformat(timespec="seconds"),
            }
            self.state.upsert_video(vid, date)
        return result

    def produce_day(self, date: str | None = None, *, limit: int | None = None) -> list[dict]:
        date = date or today_wita(self.settings)
        if self.settings.approval_mode == "required":
            selected = self.state.day(date).get("selected")
            if not selected:
                log.info("Mode required: belum ada pilihan, produce ditunda")
                return []
        vids = list(self.state.videos(date))
        if not vids:
            # belum ada antrian — jalankan scout dulu
            self.scout_and_notify()
            vids = list(self.state.videos(date))
        out = []
        n = 0
        for v in vids:
            if limit is not None and n >= limit:
                break
            if v.get("status") in {"published", "rejected", "skipped", "rendered", "approved"}:
                # rendered/approved sudah diproduksi
                if v.get("status") in {"rendered", "approved"} and v.get("mp4") and Path(v["mp4"]).exists():
                    continue
                if v.get("status") in {"published", "rejected", "skipped"}:
                    continue
            try:
                produced = self.produce_one(v, date)
                out.append(produced)
                n += 1
            except Exception as e:
                log.exception("Produksi slot %s gagal: %s", v.get("slot"), e)
                v["status"] = "failed"
                v["error"] = str(e)[:400]
                self.state.upsert_video(v, date)
                self.tg.send(f"Produksi slot {v.get('slot')} gagal: {e}")
        return out

    def produce_one(self, video: dict, date: str) -> dict:
        slot = video["slot"]
        job = _job_dir(self.settings, date, slot)
        topic = video.get("topic") or {"judul": video.get("judul"), "hook": video.get("hook")}
        script = self.writer.write(topic)
        (job / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        caps = self.writer.captions(script)
        (job / "captions.json").write_text(json.dumps(caps, ensure_ascii=False, indent=2), encoding="utf-8")
        caption = script.get("caption") or ""
        if caps.get("varian"):
            v0 = caps["varian"][0]
            caption = "\n".join(
                filter(
                    None,
                    [
                        v0.get("baris1"),
                        v0.get("isi"),
                        v0.get("cta"),
                        v0.get("pertanyaan"),
                        " ".join(v0.get("hashtag") or []),
                    ],
                )
            )
        tts = self.tts.synthesize(script["narasi_penuh"], job, stem="voice")
        if tts.duration > HARD_MAX_DURATION:
            ratio = max(0.5, (HARD_MAX_DURATION - 1.0) / tts.duration)
            max_words = max(60, int(_word_count(script["narasi_penuh"]) * ratio))
            script["narasi_penuh"] = trim_to_word_budget(script["narasi_penuh"], max_words)
            (job / "script.json").write_text(
                json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log.warning(
                "TTS %.1fs > %.0fs, naskah dipotong ke %s kata lalu disintesis ulang",
                tts.duration, HARD_MAX_DURATION, max_words,
            )
            tts = self.tts.synthesize(script["narasi_penuh"], job, stem="voice")
        (job / "words.json").write_text(
            json.dumps([{"word": w.word, "start": w.start, "duration": w.duration} for w in tts.words],
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        chunks = chunk_captions(tts.words, audio_duration=min(tts.duration, HARD_MAX_DURATION))
        (job / "chunks.json").write_text(
            json.dumps(
                [
                    {
                        "text": c.text,
                        "start": c.start,
                        "end": c.end,
                        "words": [{"word": w.word, "start": w.start, "duration": w.duration} for w in c.words],
                    }
                    for c in chunks
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        bg = attr = None
        query = script.get("image_query") or (script.get("adegan") or [{}])[0].get("image_query")
        # stok opsional; gagal → lokal (selalu ada)
        try:
            img = self.images.search(query or "dark creative studio", job, stem="bg")
            if img.provider_id != "local":
                bg = img.path
                attr = img.attribution
        except Exception as e:
            log.info("gambar stok dilewati: %s", e)
        mp4 = job / "reel.mp4"
        render_video(script, tts, mp4, settings=self.settings, background_photo=bg, attribution=attr or "")
        qc = inspect(mp4, words=tts.words, chunks=chunks)
        (job / "qc.json").write_text(json.dumps(qc.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        video.update({
            "status": "rendered",
            "mp4": str(mp4),
            "script_path": str(job / "script.json"),
            "caption": caption,
            "tts_provider": tts.provider_id,
            "llm_provider": script.get("llm_provider"),
            "qc_ok": qc.ok,
            "qc": {"lufs": qc.integrated_lufs, "peak": qc.true_peak_dbtp, "duration": qc.duration, "errors": qc.errors},
            "judul": script.get("judul") or video.get("judul"),
        })
        if not qc.ok:
            video["status"] = "qc_failed"
        self.state.upsert_video(video, date)
        self.state.add_past_topic(video.get("judul") or "", angle=script.get("angle"), slot=slot)
        self.tg.send_preview(video, mp4 if qc.ok else None)
        log.info("Slot %s siap: %s\n%s", slot, mp4, report_text(qc))
        return video

    def publish_slot(self, slot: int, date: str | None = None) -> dict:
        date = date or today_wita(self.settings)
        # poll telegram dulu (veto terakhir)
        try:
            if not self.settings.dry_run:
                self.tg.poll()
        except Exception as e:
            log.warning("poll sebelum publish: %s", e)
        if self.state.is_paused():
            return {"ok": False, "reason": "paused", "slot": slot}
        v = self.state.video_by_slot(slot, date)
        if not v:
            return {"ok": False, "reason": "no_video", "slot": slot}
        if v.get("status") in {"rejected", "skipped", "published"}:
            return {"ok": False, "reason": v["status"], "slot": slot}
        if v.get("status") == "qc_failed":
            return {"ok": False, "reason": "qc_failed", "slot": slot}
        if self.settings.approval_mode == "required" and v.get("status") != "approved":
            return {"ok": False, "reason": "awaiting_approval", "slot": slot}
        mp4 = Path(v.get("mp4") or "")
        if not mp4.exists():
            # fallback: produksi ulang dari topik
            v = self.produce_one(v, date)
            mp4 = Path(v.get("mp4") or "")
        if not mp4.exists():
            return {"ok": False, "reason": "mp4_missing", "slot": slot}

        # Gerbang QC pra-publish: durasi & timing caption wajib lolos.
        try:
            gate = pre_publish_gate(mp4, words=_load_job_words(v))
        except QCRejected as e:
            v["status"] = "qc_failed"
            v["qc_ok"] = False
            v["qc"] = e.result.to_dict()
            self.state.upsert_video(v, date)
            log.warning("Publish slot %s ditolak QC: %s", slot, e)
            return {"ok": False, "reason": "qc_failed", "slot": slot, "errors": e.result.errors}

        # waktu SCHEDULED untuk FB: jika kita publish tepat di jam slot, PUBLISHED langsung
        slot_meta = next((s for s in SLOTS if s["id"] == slot), None)
        when = None
        result = self.publisher.publish(
            mp4,
            caption=v.get("caption") or "",
            when_unix=when,
            video_state="PUBLISHED",
        )
        v["status"] = "published" if not self.settings.dry_run else "dry_published"
        v["publish"] = {k: result.get(k) for k in ("dry_run", "fb", "ig", "host", "dry_run_path")}
        v["published_at"] = datetime.now(self.settings.tz).isoformat(timespec="seconds")
        self.state.upsert_video(v, date)
        self.tg.send(
            f"{'DRY-RUN ' if self.settings.dry_run else ''}Slot {slot} "
            f"({v.get('slot_label')} WITA) — {v.get('judul')}\n"
            f"Status: {v['status']}"
        )
        return {"ok": True, "video": v, "publish": result}

    def run_once(self, *, topic: dict | None = None) -> dict:
        """Satu video end-to-end (untuk tes lokal), default DRY_RUN."""
        date = today_wita(self.settings)
        if topic is None:
            scouted = self.scout.run(use_llm=False)
            topic = (scouted.get("shortlist") or [None])[0] or {
                "judul": "Kenapa video AI bisa tayang tanpa kamera",
                "hook": "Kamu nggak perlu kamera untuk mulai unggah Reels.",
            }
        video = {
            "id": f"{date}-once-{uuid.uuid4().hex[:6]}",
            "slot": 1,
            "slot_label": "tes",
            "judul": topic.get("judul"),
            "hook": topic.get("hook"),
            "topic": topic,
            "status": "pending",
        }
        produced = self.produce_one(video, date)
        pub = self.publisher.publish(
            Path(produced["mp4"]),
            caption=produced.get("caption") or "",
        )
        return {"video": produced, "publish": pub}

    def sample(self, dest: Path | None = None) -> dict:
        """Render sampel resmi ke samples/, pakai naskah tetap (tanpa LLM)."""
        dest = dest or (self.settings.samples_dir / "sample_reel.mp4")
        script_path = self.settings.data_dir / "sample_script.json"
        script = json.loads(script_path.read_text(encoding="utf-8"))
        job = self.settings.samples_dir / "_build"
        job.mkdir(parents=True, exist_ok=True)
        tts = self.tts.synthesize(script["narasi_penuh"], job, stem="sample_voice")
        mp4 = render_video(script, tts, dest, settings=self.settings)
        qc = inspect(mp4)
        report = report_text(qc)
        (self.settings.samples_dir / "sample_qc.json").write_text(
            json.dumps(qc.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.settings.samples_dir / "sample_qc.txt").write_text(report + "\n", encoding="utf-8")
        log.info(report)
        return {"mp4": str(mp4), "qc": qc.to_dict(), "tts_provider": tts.provider_id, "duration": tts.duration}
