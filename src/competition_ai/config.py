from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1","true","yes","on"}

@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    api_url: str = os.getenv(
        "THAILLM_API_URL",
        "https://thaillm.or.th/api/v1/chat/completions"
    )
    api_key: str = os.getenv("THAILLM_API_KEY", "").strip()
    model: str = os.getenv("THAILLM_MODEL", "openthaigpt").strip()

    timeout: int = int(os.getenv("THAILLM_TIMEOUT_SECONDS", "120"))
    retries: int = int(os.getenv("THAILLM_MAX_RETRIES", "2"))
    max_tokens: int = int(os.getenv("THAILLM_MAX_TOKENS", "1600"))
    temperature: float = float(os.getenv("THAILLM_TEMPERATURE", "0"))

    strict_document_flow: bool = _bool("STRICT_THAILLM_DOCUMENT_FLOW", True)
    use_query_planner: bool = _bool("USE_THAILLM_QUERY_PLANNER", True)
    use_rerank: bool = _bool("USE_THAILLM_RERANK", True)
    verify_answers: bool = _bool("VERIFY_ANSWERS", True)
    answer_repair: bool = _bool("ENABLE_ANSWER_REPAIR", True)
    enable_cache: bool = _bool("ENABLE_CACHE", True)
    debug: bool = _bool("DEBUG_MODE", False)

    top_candidates: int = int(os.getenv("TOP_CANDIDATES", "16"))
    evidence_k: int = int(os.getenv("FINAL_EVIDENCE_K", "6"))
    cache_ttl: int = int(os.getenv("CACHE_TTL_SECONDS", "86400"))

SETTINGS = Settings()
