"""Rantai LLM gratis: Gemini → Groq → OpenRouter → Cloudflare → HuggingFace → template."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from reels_autopilot.config import Settings, get_settings
from reels_autopilot.providers.router import ProviderRouter, QuotaExhausted, parse_retry_after

log = logging.getLogger("reels.llm")
TIMEOUT = 60


def _quota(provider_id: str, resp: requests.Response) -> None:
    text = (resp.text or "")[:800]
    if resp.status_code in {429, 402} or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
        raise QuotaExhausted(
            provider_id,
            f"HTTP {resp.status_code}: {text[:300]}",
            retry_after=parse_retry_after(resp.headers.get("Retry-After")),
        )


def extract_json(text: str) -> Any:
    """Ambil JSON dari teks LLM (boleh terbungkus fence markdown)."""
    if not text:
        raise ValueError("jawaban LLM kosong")
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        return json.loads(raw[start : end + 1])
    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end > start:
        return json.loads(raw[start : end + 1])
    raise ValueError(f"tidak ada JSON di jawaban LLM: {raw[:200]}")


class LLMClient:
    def __init__(self, settings: Settings | None = None, router: ProviderRouter | None = None):
        self.settings = settings or get_settings()
        self.router = router or ProviderRouter(self.settings)

    def generate(self, prompt: str, *, system: str = "", json_mode: bool = True) -> tuple[str, str]:
        """Kembalikan (teks, provider_id)."""
        s = self.settings
        callers = {}

        if s.gemini_api_key:
            callers["gemini"] = lambda: self._gemini(prompt, system, json_mode)
        if s.groq_api_key:
            callers["groq"] = lambda: self._openai_compat(
                "groq",
                "https://api.groq.com/openai/v1/chat/completions",
                s.groq_api_key,
                s.groq_model,
                prompt,
                system,
                json_mode,
            )
        if s.github_models_token:
            callers["github_models"] = lambda: self._github_models(prompt, system, json_mode)
        if s.openrouter_api_key:
            callers["openrouter"] = lambda: self._openai_compat(
                "openrouter",
                "https://openrouter.ai/api/v1/chat/completions",
                s.openrouter_api_key,
                s.openrouter_model,
                prompt,
                system,
                json_mode,
                extra_headers={
                    "HTTP-Referer": "https://github.com/reels-autopilot",
                    "X-Title": "reels-autopilot Po Chai",
                },
            )
        if s.cf_account_id and s.cf_api_token:
            callers["cloudflare"] = lambda: self._cloudflare(prompt, system)
        if s.hf_token:
            callers["huggingface"] = lambda: self._huggingface(prompt, system)
        callers["template"] = lambda: (_template_notice(prompt),)[0] if False else _template_notice(prompt)

        result = self.router.execute("llm", callers)
        return result.value, result.provider_id

    def generate_json(self, prompt: str, *, system: str = "") -> tuple[Any, str]:
        text, provider = self.generate(prompt, system=system, json_mode=True)
        if provider == "template":
            # pemanggil harus menangani 'template' dengan fallback sendiri
            return {"_template": True, "_raw": text}, provider
        return extract_json(text), provider

    def _gemini(self, prompt: str, system: str, json_mode: bool) -> str:
        s = self.settings
        models = [
            s.gemini_model,
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.5-flash",
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
            "gemini-3.1-flash-lite",
        ]
        seen = set()
        last_err: Exception | None = None
        for model in models:
            if not model or model in seen:
                continue
            seen.add(model)
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent"
            )
            body: dict[str, Any] = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4096},
            }
            if json_mode:
                body["generationConfig"]["responseMimeType"] = "application/json"
            if system:
                body["systemInstruction"] = {"parts": [{"text": system}]}
            try:
                resp = requests.post(
                    url,
                    json=body,
                    headers={"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"},
                    timeout=TIMEOUT,
                )
            except requests.RequestException as e:
                last_err = e
                continue
            _quota("gemini", resp)
            if resp.status_code >= 400:
                last_err = RuntimeError(f"gemini {model} HTTP {resp.status_code}: {resp.text[:300]}")
                # 404/400: nama model usang; 503: demand tinggi — coba model lain
                if resp.status_code in {400, 404, 503}:
                    continue
                raise last_err
            data = resp.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError) as e:
                last_err = RuntimeError(f"gemini response aneh: {e} {str(data)[:200]}")
                raise last_err
        raise last_err or RuntimeError("gemini gagal tanpa pesan")

    def _openai_compat(
        self,
        provider_id: str,
        url: str,
        key: str,
        model: str,
        prompt: str,
        system: str,
        json_mode: bool,
        extra_headers: dict | None = None,
    ) -> str:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.4}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        resp = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
        _quota(provider_id, resp)
        if resp.status_code >= 400:
            # beberapa model free tidak mendukung response_format
            if json_mode and resp.status_code in {400, 422}:
                body.pop("response_format", None)
                resp = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
                _quota(provider_id, resp)
            if resp.status_code >= 400:
                raise RuntimeError(f"{provider_id} HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"{provider_id} response aneh: {e} {str(data)[:200]}") from e

    def _github_models(self, prompt: str, system: str, json_mode: bool) -> str:
        """GitHub Models resmi (OpenAI-compatible). Coba host baru, lalu host Azure lama."""
        s = self.settings
        endpoints = [
            "https://models.github.ai/inference/chat/completions",
            "https://models.inference.ai.azure.com/chat/completions",
        ]
        last_err: Exception | None = None
        for url in endpoints:
            try:
                return self._openai_compat(
                    "github_models",
                    url,
                    s.github_models_token,
                    s.github_models_model,
                    prompt,
                    system,
                    json_mode,
                    extra_headers={
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
            except Exception as e:
                last_err = e
                continue
        raise last_err or RuntimeError("github_models gagal")

    def _cloudflare(self, prompt: str, system: str) -> str:
        s = self.settings
        url = (
            f"https://api.cloudflare.com/client/v4/accounts/{s.cf_account_id}"
            f"/ai/run/{s.cf_ai_model}"
        )
        headers = {"Authorization": f"Bearer {s.cf_api_token}", "Content-Type": "application/json"}
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = requests.post(url, headers=headers, json={"messages": messages}, timeout=TIMEOUT)
        _quota("cloudflare", resp)
        if resp.status_code >= 400:
            raise RuntimeError(f"cloudflare HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        result = data.get("result") or data
        if isinstance(result, dict):
            for key in ("response", "text", "output", "content"):
                if key in result and isinstance(result[key], str):
                    return result[key]
            if "message" in result and isinstance(result["message"], dict):
                return result["message"].get("content") or ""
        if isinstance(result, str):
            return result
        raise RuntimeError(f"cloudflare response aneh: {str(data)[:200]}")

    def _huggingface(self, prompt: str, system: str) -> str:
        s = self.settings
        headers = {"Authorization": f"Bearer {s.hf_token}", "Content-Type": "application/json"}
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        # jalur baru (Inference Providers, OpenAI-compatible)
        url = "https://router.huggingface.co/v1/chat/completions"
        body = {"model": s.hf_model, "messages": messages, "temperature": 0.4}
        resp = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
        if resp.status_code in {404, 422, 400}:
            # jalur lama
            url2 = f"https://api-inference.huggingface.co/models/{s.hf_model}"
            full = (system + "\n\n" + prompt).strip()
            resp = requests.post(url2, headers=headers, json={"inputs": full}, timeout=TIMEOUT)
            _quota("huggingface", resp)
            if resp.status_code >= 400:
                raise RuntimeError(f"huggingface HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0].get("generated_text") or str(data[0])
            if isinstance(data, dict):
                return data.get("generated_text") or data.get("text") or str(data)
            return str(data)
        _quota("huggingface", resp)
        if resp.status_code >= 400:
            raise RuntimeError(f"huggingface HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _template_notice(prompt: str) -> str:
    # Penanda agar pemanggil memakai fallback template (bukan mengarang JSON palsu dari LLM)
    return json.dumps({"_template": True, "note": "LLM tidak tersedia, pakai template lokal"})
