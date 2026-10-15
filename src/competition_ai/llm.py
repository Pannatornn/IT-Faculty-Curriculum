from __future__ import annotations
import json
import re
import time
import requests
from .config import Settings

class ThaiLLMError(RuntimeError):
    pass

def strip_think(text: str) -> str:
    text = text or ""
    text = re.sub(
        r"<think>.*?</think>",
        "",
        text,
        flags=re.S | re.I
    )
    return text.strip()

def extract_json(text: str):
    text = strip_think(text)

    try:
        return json.loads(text)
    except Exception:
        pass

    fence = re.search(
        r"```(?:json)?\s*(.*?)```",
        text,
        flags=re.S | re.I
    )

    if fence:
        try:
            return json.loads(
                fence.group(1).strip()
            )
        except Exception:
            pass

    starts = [
        i for i, ch in enumerate(text)
        if ch in "[{"
    ]

    for start in starts:
        for end in range(
            len(text),
            start,
            -1
        ):
            if text[end-1] not in "]}":
                continue

            try:
                return json.loads(
                    text[start:end]
                )
            except Exception:
                continue

    raise ValueError(
        "ThaiLLM did not return valid JSON"
    )

class ThaiLLMClient:
    def __init__(self, settings: Settings):
        self.s = settings

        if not self.s.api_key:
            raise ThaiLLMError(
                "ยังไม่ได้ตั้ง THAILLM_API_KEY ในไฟล์ .env"
            )

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None
    ) -> str:
        payload = {
            "model": self.s.model,
            "messages": [
                {
                    "role":"system",
                    "content":system
                },
                {
                    "role":"user",
                    "content":user
                },
            ],
            "max_tokens": (
                max_tokens
                or self.s.max_tokens
            ),
            "temperature": self.s.temperature,
        }

        headers = {
            "Authorization":
                "Bearer " + self.s.api_key,
            "Content-Type":
                "application/json",
        }

        last = None

        for attempt in range(
            self.s.retries + 1
        ):
            remaining = (
                self.s.request_deadline - time.monotonic()
                if self.s.request_deadline is not None else float(self.s.timeout)
            )
            if remaining <= 0:
                raise ThaiLLMError("Request time limit exceeded. Please retry.")
            try:
                r = requests.post(
                    self.s.api_url,
                    headers=headers,
                    json=payload,
                    timeout=max(0.1, min(float(self.s.timeout), remaining))
                )

                if r.status_code >= 400:
                    raise ThaiLLMError(
                        f"HTTP {r.status_code}: "
                        f"{r.text[:400]}"
                    )

                data = r.json()

                if "choices" not in data:
                    raise ThaiLLMError(
                        "รูปแบบ API response "
                        "ไม่ถูกต้อง"
                    )

                return strip_think(
                    data["choices"][0]
                        ["message"]
                        ["content"]
                )

            except Exception as exc:
                last = exc

                if attempt < self.s.retries:
                    pause = 0.6 * (attempt + 1)
                    if self.s.request_deadline is not None:
                        pause = min(pause, max(0, self.s.request_deadline - time.monotonic()))
                    time.sleep(pause)

        raise ThaiLLMError(
            f"ThaiLLM API ล้มเหลว: {last}"
        )

    def generate_json(
        self,
        system: str,
        user: str
    ):
        raw = self.generate(
            system,
            user
        )

        try:
            return extract_json(raw), raw

        except Exception:
            repair = self.generate(
                "คุณเป็น JSON repair engine "
                "ห้ามอธิบาย ห้ามมี <think> "
                "คืน JSON ที่ถูกต้องเท่านั้น",
                "แก้ข้อความต่อไปนี้ให้เป็น "
                "JSON ที่ถูกต้อง โดยรักษา "
                "ความหมายเดิม:\n\n" + raw,
                max_tokens=900,
            )

            return extract_json(repair), raw
