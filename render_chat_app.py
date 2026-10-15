from __future__ import annotations

import asyncio
import os
import re

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

import render_app_v2 as legacy
import render_server as core
from chat_ui import render_chat_ui
from chat_ui_finish_patch import inject_final_ui_patch
from chat_ui_patch import inject_chat_runtime_patch
from citation_view import serve_document
from staff_access import require_staff, staff_session
from competition_ai.grading_policy import classify_grader_edge
from competition_ai.hard_policy import classify_hard_edge, is_all_program_question
from competition_ai.policy import classify_pre_route, detect_language
from competition_ai.policy_pipeline import PROGRAM_LIST_PATTERNS
from competition_ai.router import detect_programs


# Short questions such as "แล้วเรียนกี่ปี?" have no domain keyword until a
# program is supplied. Only these curriculum topics can acquire that context;
# an arbitrary out-of-scope question must not become valid just by adding AIT.
FOLLOWUP_TOPIC_RE = re.compile(
    r"เรียน(?:กี่ปี|นาน|ภาษา|อะไร|จบ)|ระยะเวลา(?:เรียน)?|หมวดวิชา|"
    r"ความเชี่ยวชาญ|แขนง|ฝึกงาน|แผนการเรียน|ทักษะ|"
    r"\b(?:credits?|courses?|speciali[sz]ations?|tracks?|internships?|"
    r"prerequisites?|careers?|skills?)\b|"
    r"\b(?:how\s+long|how\s+many\s+years)\s*(?:\?|$)|"
    r"\b(?:how\s+long|how\s+many\s+years).*(?:study|graduate|program|\bit\b)|"
    r"\blanguage\b.*\b(?:teach|taught|instruction|study|used)\b|"
    r"(?:学制|几年|教学语言|就业|实习|方向)",
    re.I,
)

CONTEXT_RESET_RE = re.compile(
    r"เปลี่ยนเรื่อง|อีกเรื่อง(?:หนึ่ง)?|ไม่เกี่ยวกับ(?:เรื่อง|คำถาม)(?:เดิม|ก่อน)|"
    r"\b(?:new\s+topic|change\s+(?:the\s+)?(?:topic|subject)|unrelated\s+question)\b|"
    r"换个话题|另一个话题",
    re.I,
)

CHAT_TIMEOUT_SECONDS = 90
MAX_QUESTION_CHARS = 4000
MAX_HISTORY_CONTENT_CHARS = 16000

RETRY_REFERENCE_RE = re.compile(
    r"^\s*(?:"
    r"เช็ค(?:ดู)?(?:ดิ|สิ|หน่อย)?|เช็ก(?:ดู)?(?:ดิ|สิ|หน่อย)?|"
    r"ลองเช็ค(?:ดู)?|ลองเช็ก(?:ดู)?|ตรวจ(?:ดู)?(?:ดิ|สิ|หน่อย)?|"
    r"ดูอีกที|ลองใหม่|ตอบใหม่|"
    r"check(?:\s+it)?(?:\s+again)?|recheck|try\s+again|look\s+again|"
    r"再查一下|再看看|检查一下"
    r")\s*[!?…。]*\s*$",
    re.I,
)


def chat_config() -> dict[str, object]:
    url = os.getenv("SUPABASE_URL", "").strip()
    anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    return {
        "supabaseUrl": url,
        "supabaseAnonKey": anon_key,
        "authConfigured": bool(url and anon_key),
        "modelDisplay": core.MODEL_DISPLAY,
    }


def _recent_user_programs(history: list[dict]) -> list[str]:
    """Recover explicit program context from recent user turns only.

    Assistant answers can mention many curricula, so they are intentionally not
    used for routing context. The nearest user turn that names a program wins.
    An unrelated or blocked user turn ends the previous curriculum topic.
    """
    for item in reversed(history[-10:]):
        if str(item.get("role", "")).casefold() != "user":
            continue
        text = item.get("content", "")
        if not isinstance(text, str):
            return []
        text = text.strip()
        if not text:
            continue
        if RETRY_REFERENCE_RE.search(text):
            continue
        if not _can_inherit_program_context(text):
            return []
        programs = detect_programs(text, core.CATALOG)
        if programs:
            return programs
    return []


def _latest_user_question(history: list[dict]) -> str:
    for item in reversed(history[-10:]):
        if str(item.get("role", "")).casefold() != "user":
            continue
        text = item.get("content", "")
        if not isinstance(text, str):
            return ""
        text = text.strip()
        if text and not RETRY_REFERENCE_RE.search(text):
            return text
    return ""


def _can_inherit_program_context(question: str) -> bool:
    """Keep context within safe curriculum questions, including short follow-ups."""
    if CONTEXT_RESET_RE.search(question) or is_all_program_question(question):
        return False
    if any(re.search(pattern, question, re.I) for pattern in PROGRAM_LIST_PATTERNS):
        return False
    if classify_hard_edge(question) or classify_grader_edge(question):
        return False

    decision = classify_pre_route(question)
    if decision is None:
        return True
    # A missing domain keyword is expected for "How long?", but a known
    # off-topic topic (weather, another university, etc.) remains out of scope
    # even after adding a program name. Never soften a policy decision.
    if decision.kind != "OUT_OF_SCOPE" or not FOLLOWUP_TOPIC_RE.search(question):
        return False
    contextual = _program_context_question(question, "AIT")
    return classify_pre_route(contextual) is None


def _contextual_retry_question(question: str, history: list[dict]) -> str | None:
    """Turn vague retry turns such as 'เช็คดูดิ' into a grounded re-check.

    Only prior *user* text is reused. Assistant text is never copied into the
    effective query, preventing model output from becoming routing authority.
    """
    if not RETRY_REFERENCE_RE.search(question or ""):
        return None
    previous = _latest_user_question(history)
    if not previous:
        return None

    lang = detect_language(question)
    if lang == "th":
        return f"โปรดตรวจสอบคำถามก่อนหน้านี้อีกครั้งและตอบเป็นภาษาไทย: {previous}"
    if lang == "zh":
        return f"请重新检查上一个问题，并用中文回答：{previous}"
    return f"Please re-check the previous question and answer in English: {previous}"


def _program_context_question(question: str, program: str) -> str:
    """Make short follow-ups pass pre-route scope checks without changing intent."""
    lang = detect_language(question)
    if lang == "th":
        return f"ในบริบทหลักสูตร {program}: {question}"
    if lang == "zh":
        return f"关于 {program} 课程：{question}"
    return f"In the {program} curriculum context: {question}"


def _answer_chat(question: str, history: list[dict], pipeline):
    """Resolve explicit user program scope before entering the shared pipeline.

    route_question may infer *all* programs from words such as "which" or
    "กับ". That is not an explicit program selection and must not override the
    conversation's nearest user-specified program or comparison group.
    """
    retry_question = _contextual_retry_question(question, history)
    effective_question = retry_question or question
    contextualized = bool(retry_question)

    if (
        not detect_programs(effective_question, core.CATALOG)
        and _can_inherit_program_context(effective_question)
    ):
        recent_programs = _recent_user_programs(history)
        if recent_programs:
            effective_question = _program_context_question(
                effective_question, " vs ".join(recent_programs)
            )
            contextualized = True

    # Use ask for comparisons too: it applies policy checks, balanced retrieval,
    # and the same resilient fallbacks as a question with explicit programs.
    result = pipeline.ask(effective_question)
    if contextualized:
        result = pipeline._ensure_answer_language(question, result)
    return result, contextualized


async def root(_: Request):
    html = inject_chat_runtime_patch(render_chat_ui(chat_config()))
    html = inject_final_ui_patch(html)
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
        },
    )


async def api_chat_config(_: Request):
    # Supabase anon keys are intentionally public browser credentials. Row-level
    # security in supabase/schema.sql is what protects each user's chat data.
    return JSONResponse(chat_config())


async def api_chat(req: Request):
    if x := core.limited(req, "chat"):
        return x

    try:
        body = await req.json()
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"error": "body must be valid JSON"}, status_code=400)

    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    raw_question = body.get("question")
    if not isinstance(raw_question, str) or not raw_question.strip():
        return JSONResponse({"error": "question must be a non-empty string"}, status_code=400)
    if len(raw_question) > MAX_QUESTION_CHARS:
        return JSONResponse(
            {"error": f"question is limited to {MAX_QUESTION_CHARS} characters"},
            status_code=400,
        )
    question = raw_question.strip()
    history = body.get("history", [])
    if not isinstance(history, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("role"), str)
        or item.get("role") not in {"user", "assistant"}
        or not isinstance(item.get("content"), str)
        or len(item["content"]) > MAX_HISTORY_CONTENT_CHARS
        for item in history
    ):
        return JSONResponse(
            {"error": "history must contain user or assistant messages with string content"},
            status_code=400,
        )
    history = [{"role": item["role"], "content": item["content"]} for item in history[-10:]]

    try:
        # Retrieval and the ThaiLLM client are synchronous. Keeping them off the
        # event loop allows other requests and client cancellation to proceed.
        result, contextualized = await asyncio.wait_for(
            run_in_threadpool(lambda: _answer_chat(question, history, legacy.resilient_pipe(req))),
            timeout=CHAT_TIMEOUT_SECONDS,
        )
        payload = core.response_payload(question, result)
        payload["contextualized"] = contextualized
        return JSONResponse(payload)
    except TimeoutError:
        return JSONResponse(
            {
                "error": "The answer took too long. Please try again.",
                "type": "TIMEOUT",
                "retryable": True,
            },
            status_code=504,
        )
    except Exception as exc:
        # Keep the conversational surface non-empty even during transient
        # upstream failures, matching the competition batch invariant.
        fallback = legacy.nonempty_error_result(
            question,
            core.clean_error(exc),
        )
        payload = core.response_payload(question, fallback)
        payload["degraded"] = True
        payload["contextualized"] = False
        return JSONResponse(payload, status_code=200)


def staff_only(handler):
    async def guarded(req: Request):
        if denied := require_staff(req):
            return denied
        return await handler(req)
    return guarded


routes = [
    Route("/", root),
    Route("/favicon.ico", core.favicon),
    Route("/healthz", core.healthz),
    Route("/api/chat-config", api_chat_config),
    Route("/api/health", core.api_health),
    Route("/api/programs", core.api_programs),
    Route("/api/chat", api_chat, methods=["POST"]),
    Route("/api/staff/session", staff_session, methods=["GET", "POST", "DELETE"]),
    Route("/documents/{filename}", serve_document, methods=["GET", "HEAD"]),
    Route("/api/ask", legacy.api_ask, methods=["POST"]),
    Route("/api/compare", core.api_compare, methods=["POST"]),
    Route("/api/import-questions", staff_only(core.api_import_questions), methods=["POST"]),
    Route("/api/run-batch", staff_only(legacy.api_run_batch), methods=["POST"]),
    Route("/api/benchmark", staff_only(core.api_benchmark), methods=["POST"]),
]

app = Starlette(routes=routes, debug=False)


async def response_headers(req: Request, call_next):
    response = await call_next(req)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if req.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.add_middleware(BaseHTTPMiddleware, dispatch=response_headers)
