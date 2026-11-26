"""One wrapper for every structured (JSON-schema) LLM call in LevelUpCorp.

Every LLM step (resume parsing, job scoring, form answers, email classification)
goes through `LLM.json()`, which forces the reply to match a JSON schema, so the
rest of the code never has to parse free text.

Two providers:
  * anthropic - Claude via the Anthropic SDK (needs ANTHROPIC_API_KEY).
  * groq      - free tier, OpenAI-compatible API (needs GROQ_API_KEY). A chain of models
                is tried in order; when one hits its per-minute token limit the next one
                takes over (the same routing + fallback idea as the OpenClaw agent).
`llm.provider: auto` (default) picks anthropic if its key exists, else groq.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

import requests

log = logging.getLogger(__name__)

# Claude models that accept the server-side refusal fallback (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5",
                    "claude-fable-5-2", "claude-fable-5-1"}

OPENAI_COMPAT = {
    "groq": {"base": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
             "chain": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]},
    "openrouter": {"base": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY", "chain": []},
    "nvidia": {"base": "https://integrate.api.nvidia.com/v1", "key_env": "NVIDIA_API_KEY", "chain": []},
}


class LLMError(RuntimeError):
    pass


def _flatten(user: Any) -> str:
    """Content blocks -> plain text (OpenAI-compatible providers take text only)."""
    if isinstance(user, str):
        return user
    parts = []
    for b in user:
        if b.get("type") == "text":
            parts.append(b["text"])
        elif b.get("type") == "document":
            raise LLMError("This provider can't read PDF files directly; give `setup` a .docx resume.")
    return "\n\n".join(parts)


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _seconds(v: Optional[str]) -> float:
    """Parse Groq reset headers like '3.8s', '1m26.4s', '120ms'."""
    if not v:
        return 0.0
    try:
        return float(v)
    except ValueError:
        pass
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)(ms|s|m|h)", v):
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total


class LLM:
    def __init__(self, model: str = "claude-opus-5-5", models: Optional[dict] = None,
                 provider: str = "auto", chain: Optional[list] = None, max_output_tokens: int = 4000):
        if provider == "auto":
            provider = "anthropic" if os.getenv("ANTHROPIC_API_KEY") else (
                "groq" if os.getenv("GROQ_API_KEY") else "anthropic")
        self.provider = provider
        self.models = models or {}          # optional per-task override
        self.usage = {"input": 0, "output": 0, "cache_read": 0, "calls": 0, "by_model": {}}
        self.max_output_tokens = int(max_output_tokens)
        if provider == "anthropic":
            import anthropic
            try:
                self.client = anthropic.Anthropic(max_retries=4)
            except anthropic.AnthropicError as e:
                raise SystemExit("No LLM key found. Put GROQ_API_KEY=... (free) or ANTHROPIC_API_KEY=... in .env.") from e
            self.default_model = model
            return
        spec = OPENAI_COMPAT.get(provider)
        if not spec:
            raise SystemExit(f"Unknown llm.provider '{provider}'. Use auto, anthropic, groq, openrouter or nvidia.")
        self.key = os.getenv(spec["key_env"])
        if not self.key:
            raise SystemExit(f"{spec['key_env']} is not set in .env.")
        self.base = spec["base"]
        self.chain = list(chain or spec["chain"])
        if not self.chain:
            raise SystemExit(f"Set llm.chain (list of model ids) in config.yaml for provider {provider}.")
        self.default_model = self.chain[0]
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        self._cooldown: dict[str, float] = {}   # model -> time it may be used again

    def model_for(self, task: str) -> str:
        return self.models.get(task) or self.default_model

    # ------------------------------------------------------------------ public
    def json(self, *, task: str, system: str, user: Any, schema: dict,
             effort: str = "low", max_tokens: int = 16000) -> dict:
        """Run one structured call. `user` may be a string or a list of content blocks."""
        if self.provider == "anthropic":
            return self._anthropic(task, system, user, schema, effort, max_tokens)
        return self._openai_compat(task, system, _flatten(user), schema, effort,
                                   min(max_tokens, self.max_output_tokens))

    # --------------------------------------------------------------- anthropic
    def _anthropic(self, task, system, user, schema, effort, max_tokens) -> dict:
        import anthropic
        model = self.model_for(task)
        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            if model in _FALLBACK_MODELS:
                resp = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise LLMError("Claude API key is missing or invalid.") from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"Claude rejected the request ({task}): {e.message}") from e
        except anthropic.RateLimitError as e:
            raise LLMError(f"Claude rate limit hit during {task}; try again later.") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Could not reach the Claude API - check your internet connection.") from e
        u = resp.usage
        self._count(model, getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0)
        self.usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        if resp.stop_reason == "refusal":
            raise LLMError(f"Claude declined the {task} request.")
        if resp.stop_reason == "max_tokens":
            raise LLMError(f"Claude ran out of output tokens during {task}; raise max_tokens.")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"Claude returned invalid JSON for {task}") from e

    # ------------------------------------------------------- openai-compatible
    def _openai_compat(self, task, system, user, schema, effort, max_tokens) -> dict:
        first = self.models.get(task)
        chain = ([first] if first else []) + [m for m in self.chain if m != first]
        schema_hint = ("\n\nReply with ONE JSON object only (no prose, no code fences) that matches this "
                       f"JSON schema:\n{json.dumps(schema, ensure_ascii=False)}")
        last_err = "no model tried"
        deadline = time.time() + 240          # give up on this call after 4 minutes of rate limiting
        while time.time() < deadline:
            waits = []
            for model in chain:
                ready_at = self._cooldown.get(model, 0)
                if ready_at > time.time():
                    waits.append(ready_at - time.time())
                    continue
                body = {
                    "model": model,
                    "messages": [{"role": "system", "content": system + schema_hint},
                                 {"role": "user", "content": user}],
                    "temperature": 0.2,
                    "max_completion_tokens": max_tokens,
                    "response_format": {"type": "json_schema",
                                        "json_schema": {"name": task, "schema": schema, "strict": False}},
                }
                if model.startswith("openai/gpt-oss"):
                    body["reasoning_effort"] = "low" if effort in ("low", "medium") else "medium"
                elif model.startswith("qwen/"):
                    body["reasoning_effort"] = "none"
                try:
                    r = self.session.post(f"{self.base}/chat/completions", json=body, timeout=120)
                except requests.RequestException as e:
                    last_err = f"network error: {e}"
                    self._cooldown[model] = time.time() + 10
                    continue
                if r.status_code == 429 or r.status_code == 503:
                    wait = max(_seconds(r.headers.get("retry-after")),
                               _seconds(r.headers.get("x-ratelimit-reset-tokens")), 2.0)
                    self._cooldown[model] = time.time() + min(wait, 90)
                    last_err = f"{model} rate-limited ({r.status_code})"
                    log.info("    llm: %s rate-limited, switching model", model)
                    continue
                if r.status_code == 413:
                    raise LLMError(f"{task} prompt too large for the free tier ({model})")
                if r.status_code >= 400:
                    msg = r.text[:300]
                    if "json_schema" in msg or "response_format" in msg:
                        # model can't do schema mode: retry once in plain JSON mode
                        body["response_format"] = {"type": "json_object"}
                        r = self.session.post(f"{self.base}/chat/completions", json=body, timeout=120)
                    if r.status_code >= 400:
                        last_err = f"{model} HTTP {r.status_code}: {r.text[:200]}"
                        self._cooldown[model] = time.time() + 30
                        continue
                data = r.json()
                u = data.get("usage") or {}
                self._count(model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
                choice = (data.get("choices") or [{}])[0]
                text = (choice.get("message") or {}).get("content") or ""
                try:
                    return _parse_json(text)
                except (json.JSONDecodeError, ValueError):
                    last_err = f"{model} returned invalid JSON (finish={choice.get('finish_reason')})"
                    self._cooldown[model] = time.time() + 1
                    continue
            if waits:
                time.sleep(min(max(min(waits), 1.0), 30))
            else:
                time.sleep(2)
        raise LLMError(f"All models failed for {task}: {last_err}")

    def _count(self, model: str, inp: int, out: int) -> None:
        self.usage["calls"] += 1
        self.usage["input"] += inp or 0
        self.usage["output"] += out or 0
        self.usage["by_model"][model] = self.usage["by_model"].get(model, 0) + 1
