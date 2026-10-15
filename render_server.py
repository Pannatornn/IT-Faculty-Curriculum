from __future__ import annotations

import asyncio
import asyncio
import os
import re
import sys
import time
from collections import defaultdict, deque
from dataclasses import replace
from pathlib import Path
from typing import Any

import requests
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from citation_view import evidence_excerpt, public_answer, source_url
from competition_ai.config import SETTINGS, Settings
from competition_ai.batch_fallback import nonempty_error_result
from competition_ai.knowledge import load_catalog, load_evidence
from competition_ai.pipeline import balance_evidence_by_program
from competition_ai.policy import detect_language
from competition_ai.policy_pipeline import PolicyCompetitionPipeline
from competition_ai.question_import import decode_upload
from competition_ai.retrieval import infer_topics
from competition_ai.benchmark import load_benchmark, score_answer
from render_ui import INDEX_HTML

CATALOG = load_catalog(ROOT)
EVIDENCE = load_evidence(ROOT, CATALOG)
MODEL_DISPLAY = "OpenThaiGPT-ThaiLLM-8B-Instruct-v7.2"
PUBLIC_QUERY_TIMEOUT_SECONDS = 90

LABELS = {
    "AIT": "AIT — เทคโนโลยีปัญญาประดิษฐ์",
    "DSBA": "DSBA — วิทยาการข้อมูลและการวิเคราะห์เชิงธุรกิจ",
    "IT": "IT — เทคโนโลยีสารสนเทศ",
    "IT_INTER": "IT Inter — เทคโนโลยีสารสนเทศทางธุรกิจ (นานาชาติ)",
}

RATE = max(1, int(os.getenv("PUBLIC_RATE_LIMIT_PER_MINUTE", "30")))
BENCHMARK_COOLDOWN = max(0, int(os.getenv("BENCHMARK_COOLDOWN_SECONDS", "60")))
REQ: dict[tuple[str, str], deque[float]] = defaultdict(deque)
BENCHMARK_CACHE: dict[str, Any] | None = None
BENCHMARK_CACHE_AT = 0.0


def ip(req: Request) -> str:
    return (
        req.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (req.client.host if req.client else "unknown")
    )


def limited(req: Request, bucket: str, limit: int | None = None):
    now = time.monotonic()
    q = REQ[(ip(req), bucket)]
    while q and now - q[0] > 60:
        q.popleft()
    allowed = limit or RATE
    if len(q) >= allowed:
        retry = max(1, int(60 - (now - q[0])))
        return JSONResponse(
            {"error": "Too many requests. Please retry shortly.", "type": "RATE_LIMIT", "retryAfterSeconds": retry},
            status_code=429,
            headers={"Retry-After": str(retry)},
        )
    q.append(now)
    return None


def clean_error(exc: Exception | str) -> str:
    s = str(exc).strip()
    s = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [redacted]", s, flags=re.I)
    return (s[:380] + "…") if len(s) > 380 else (s or "Unknown error")


def transient_upstream(exc: Exception | str) -> bool:
    s = str(exc).casefold()
    return any(x in s for x in (
        "http 502", "http 503", "http 504", "bad gateway", "service unavailable",
        "gateway timeout", "timed out", "timeout", "connection reset", "remote disconnected",
    ))


def request_settings(req: Request, *, fast: bool = False) -> Settings:
    # A browser-supplied key is request-scoped. It is never written to disk,
    # logs, GitHub, or environment variables. If absent, Render's secret is used.
    supplied = req.headers.get("x-thaillm-api-key", "").strip()
    budget = max(5, min(85, int(os.getenv("THAILLM_REQUEST_TIMEOUT_SECONDS", "85"))))
    base = replace(
        SETTINGS, api_key=(supplied or SETTINGS.api_key),
        request_deadline=time.monotonic() + budget,
    )
    if fast:
        return replace(
            base,
            use_query_planner=False,
            use_rerank=False,
            verify_answers=False,
            answer_repair=False,
            retries=0,
            timeout=min(base.timeout, 75),
        )
    return base


def pipe(req: Request, *, fast: bool = False) -> PolicyCompetitionPipeline:
    return PolicyCompetitionPipeline(request_settings(req, fast=fast), CATALOG, EVIDENCE)


def confidence_of(result: Any) -> float:
    if getattr(result, "verification", None):
        try:
            return max(0.0, min(1.0, float(result.verification.confidence)))
        except Exception:
            pass
    if result.status in {"BLOCKED", "OUT_OF_SCOPE", "GREETING", "NOT_FOUND", "PARTIAL_BLOCKED"}:
        return 1.0
    return 1.0 if getattr(result, "evidence", None) and result.status == "SUPPORTED" else 0.0


def response_payload(question: str, result: Any) -> dict[str, Any]:
    conf = confidence_of(result)
    answer = public_answer(result.answer)
    status = result.status
    if not answer:
        answer = nonempty_error_result(question, "empty public answer").answer
        status = "RETRY_REQUIRED"
        conf = 0.0
    evs = [
        {
            "id": e.id,
            "sourceDoc": e.source,
            "sourceDocTitle": LABELS.get(e.program, e.program),
            "page": f"หน้า {e.page}" if e.page else "ไม่ระบุหน้า",
            "pageNumber": int(e.page or 0),
            "programCode": e.program,
            "excerpt": evidence_excerpt(e.text, question, answer),
            "quoteTh": evidence_excerpt(e.text, question, answer),
            "quoteEn": evidence_excerpt(e.text, question, answer),
            "sourceUrl": source_url(e.source, e.page),
            "confidence": conf,
        }
        for e in getattr(result, "evidence", [])
    ]
    points = []
    if getattr(result, "verification", None):
        points = list(result.verification.supported_claims)[:4]
    if not points:
        points = [
            re.sub(r"^[\-•*\d.\s]+", "", x).strip()
            for x in answer.splitlines()
            if len(x.strip()) > 12
        ][:4]

    detected_language = (getattr(result, "debug", {}) or {}).get("language") or detect_language(question)
    return {
        "question": question,
        "answer": answer,
        "answerTh": answer,
        "answerEn": answer,
        "language": detected_language,
        "status": status,
        "programDetected": (
            " / ".join(LABELS.get(x, x) for x in result.programs)
            if getattr(result, "programs", None) else None
        ),
        "confidence": conf,
        "supportedByEvidence": bool(getattr(result, "evidence", []))
        and status in {"SUPPORTED", "PARTIALLY_SUPPORTED", "CHECK_REQUIRED"},
        "securityVerdict": (
            "PROMPT_INJECTION_BLOCKED" if result.status == "BLOCKED"
            else ("OUT_OF_SCOPE" if result.status == "OUT_OF_SCOPE" else "CLEAN")
        ),
        "summaryKeyPoints": points,
        "evidenceList": evs,
        "latencyMs": int(getattr(result, "latency_ms", 0) or 0),
        "cacheHit": bool(getattr(result, "cache_hit", False)),
        "degraded": status in {"API_ERROR", "RETRY_REQUIRED", "ERROR", "TIMEOUT"},
        "model": SETTINGS.model,
        "modelDisplay": MODEL_DISPLAY,
    }


def by_topic(code: str, topic: str, limit: int = 2):
    return [
        re.sub(r"\s+", " ", str(f.get("text", ""))).strip()
        for f in CATALOG.get(code, {}).get("facts", [])
        if str(f.get("topic", "")) == topic
    ][:limit]


def matrix(left: str, right: str, focus: str):
    q = focus.casefold()
    specs = [("ภาพรวมหลักสูตร", ["basic", "duration"])]
    checks = [
        (("หน่วยกิต", "โครงสร้าง", "credit", "structure", "学分"), "โครงสร้าง/หน่วยกิต", ["structure", "basic"]),
        (("สาย", "กลุ่ม", "track", "เฉพาะ", "专业方向"), "กลุ่มวิชา/ความเชี่ยวชาญ", ["tracks"]),
        (("วิชา", "course", "ai", "machine", "deep", "nlp", "课程"), "รายวิชาสำคัญ", ["courses"]),
        (("ทักษะ", "skill", "技能"), "ทักษะและผลลัพธ์การเรียนรู้", ["skills"]),
        (("อาชีพ", "career", "งาน", "职业"), "แนวทางอาชีพ", ["career"]),
        (("ภาษา", "language", "english", "语言"), "ภาษาที่ใช้ในการเรียน", ["language"]),
    ]
    for words, label, topics in checks:
        if any(w in q for w in words):
            specs.append((label, topics))
    if len(specs) == 1:
        specs += [
            ("โครงสร้าง/หน่วยกิต", ["structure", "basic"]),
            ("กลุ่มวิชา/ความเชี่ยวชาญ", ["tracks"]),
            ("รายวิชาสำคัญ", ["courses"]),
            ("ทักษะและผลลัพธ์การเรียนรู้", ["skills"]),
            ("แนวทางอาชีพ", ["career"]),
        ]

    rows = []
    for label, topics in specs:
        def items(code: str):
            out = []
            for t in topics:
                for x in by_topic(code, t, 2):
                    if x not in out:
                        out.append(x)
                    if len(out) >= 2:
                        return out
            return out
        a, b = items(left), items(right)
        if a or b:
            rows.append({"label": label, "left": a, "right": b})
    return {
        "left": {"code": left, "display": CATALOG[left].get("display", left)},
        "right": {"code": right, "display": CATALOG[right].get("display", right)},
        "focus": focus,
        "rows": rows,
    }


def fallback_evidence(programs: list[str], focus: str, limit: int = 8):
    topics = infer_topics(focus) or {"basic", "structure", "tracks", "courses", "skills", "career"}
    selected, seen = [], set()
    for code in programs:
        for e in EVIDENCE:
            if e.program != code or e.kind != "canonical":
                continue
            topic = str(e.metadata.get("topic", "")).casefold()
            if topic in topics or topic == "basic":
                selected.append(e); seen.add(e.id); break
    for e in EVIDENCE:
        if len(selected) >= limit:
            break
        if e.program not in programs or e.kind != "canonical" or e.id in seen:
            continue
        topic = str(e.metadata.get("topic", "")).casefold()
        if topic in topics or topic in {"basic", "structure"}:
            selected.append(e); seen.add(e.id)
    return selected[:limit]


def evidence_payload(items: list[Any], confidence: float = 1.0):
    return [
        {
            "id": e.id, "sourceDoc": e.source,
            "sourceDocTitle": LABELS.get(e.program, e.program),
            "page": f"หน้า {e.page}" if e.page else "ไม่ระบุหน้า",
            "pageNumber": int(e.page or 0), "programCode": e.program,
            "quoteTh": e.text, "quoteEn": e.text, "confidence": confidence,
        }
        for e in items
    ]


def fallback_compare_payload(left: str, right: str, focus: str, language: str, exc: Exception | str):
    sc = matrix(left, right, focus)
    ev = fallback_evidence([left, right], focus)
    texts = {
        "zh": "ThaiLLM 暂时无法响应，因此下方比较表直接显示课程 canonical facts，不添加外部信息。",
        "en": "ThaiLLM is temporarily unavailable, so the comparison table below is shown directly from canonical curriculum facts. No external facts were added.",
        "th": "ThaiLLM ตอบกลับไม่สำเร็จชั่วคราว ระบบจึงแสดงตารางเปรียบเทียบจาก canonical facts ของหลักสูตรโดยตรง โดยไม่เติมข้อมูลภายนอก",
    }
    answer = texts.get(language, texts["en"])
    return {
        "question": f"compare {left} {right}", "answer": answer,
        "answerTh": answer, "answerEn": answer, "language": language,
        "status": "DEGRADED_CANONICAL", "programDetected": f"{LABELS[left]} / {LABELS[right]}",
        "confidence": 1.0, "supportedByEvidence": bool(ev), "securityVerdict": "CLEAN",
        "summaryKeyPoints": [answer], "evidenceList": evidence_payload(ev),
        "latencyMs": 0, "cacheHit": False, "left": left, "right": right,
        "focus": focus, "structuredComparison": sc, "degraded": True,
        "degradedReason": "ThaiLLM upstream temporarily unavailable", "upstreamError": clean_error(exc),
        "modelDisplay": MODEL_DISPLAY,
    }


async def root(_: Request):
    return HTMLResponse(
        INDEX_HTML,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache", "X-Content-Type-Options": "nosniff",
        },
    )


async def favicon(_: Request):
    return Response(status_code=204)


async def healthz(_: Request):
    return JSONResponse({"ok": True, "programs": len(CATALOG), "evidenceUnits": len(EVIDENCE)})


def api_health(req: Request):
    s = request_settings(req)
    ok = False
    detail = "THAILLM_API_KEY is not configured"
    if s.api_key:
        try:
            r = requests.get(
                "https://thaillm.or.th/api/v1/models",
                headers={"Authorization": "Bearer " + s.api_key}, timeout=12,
            )
            ok = r.status_code == 200
            detail = "ThaiLLM API ready" if ok else f"HTTP {r.status_code}"
        except Exception as e:
            detail = clean_error(e)
    return JSONResponse({
        "status": "online" if ok else "degraded", "apiConnected": ok, "detail": detail,
        "model": s.model, "modelDisplay": MODEL_DISPLAY, "programs": len(CATALOG),
        "evidenceUnits": len(EVIDENCE), "customKey": bool(req.headers.get("x-thaillm-api-key", "").strip()),
    })


async def api_programs(_: Request):
    return JSONResponse({"programs": [
        {"code": c, "display": CATALOG[c].get("display", c)}
        for c in ["AIT", "DSBA", "IT", "IT_INTER"] if c in CATALOG
    ]})


async def api_ask(req: Request):
    if x := limited(req, "ask"):
        return x
    try:
        b = await req.json()
        q = str(b.get("question", "")).strip()
        if not q:
            return JSONResponse({"error": "question is required"}, status_code=400)
        forced = b.get("program")
        forced = forced if forced in {"AIT", "DSBA", "IT", "IT_INTER"} else None
        r = pipe(req).ask(q, forced_program=forced)
        out = response_payload(q, r)
        if r.status == "API_ERROR":
            out["degraded"] = True
            out["degradedReason"] = "ThaiLLM upstream temporarily unavailable"
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse(
            {"error": "ระบบวิเคราะห์คำถามขัดข้องชั่วคราว", "detail": clean_error(e), "type": e.__class__.__name__},
            status_code=503 if transient_upstream(e) else 500,
        )


async def api_compare(req: Request):
    if x := limited(req, "compare"):
        return x
    try:
        b = await req.json()
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"error": "body must be valid JSON"}, status_code=400)
    if not isinstance(b, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    left, right = b.get("left"), b.get("right")
    if (
        not isinstance(left, str) or not isinstance(right, str)
        or left not in LABELS or right not in LABELS or left == right
    ):
        return JSONResponse({"error": "select two different valid programs"}, status_code=400)
    focus = b.get("focus", "")
    ui_lang = b.get("language", "TH")
    if not isinstance(focus, str) or len(focus) > 4000 or not isinstance(ui_lang, str):
        return JSONResponse({"error": "focus must be a string of at most 4000 characters"}, status_code=400)
    focus = focus.strip()
    if not focus:
        focus = "program overview, courses, skills, and careers" if ui_lang.upper() == "EN" else "ภาพรวมหลักสูตร รายวิชา ทักษะ และอาชีพ"

    def compare_report():
        language = detect_language(focus)
        q = f"{focus}\nPrograms: {left} vs {right}"
        sc = matrix(left, right, focus)
        try:
            p = pipe(req)
            r = p.compare(q, [left, right], focus)
            r = p._ensure_answer_language(q, r)
            out = response_payload(q, r)
            out.update({"left": left, "right": right, "focus": focus, "language": language, "structuredComparison": sc, "degraded": False})
            return out
        except Exception as upstream:
            return fallback_compare_payload(left, right, focus, language, upstream)

    try:
        out = await asyncio.wait_for(
            run_in_threadpool(compare_report), timeout=PUBLIC_QUERY_TIMEOUT_SECONDS,
        )
        return JSONResponse(out)
    except TimeoutError:
        return JSONResponse(
            {"error": "The comparison took too long. Please try again.", "type": "TIMEOUT", "retryable": True},
            status_code=504,
        )
    except Exception as e:
        return JSONResponse({"error": "ไม่สามารถสร้าง Comparison Report ได้", "detail": clean_error(e)}, status_code=500)


async def api_import_questions(req: Request):
    if x := limited(req, "import", limit=max(5, RATE)):
        return x
    try:
        raw = bytearray()
        async for chunk in req.stream():
            raw.extend(chunk)
            if len(raw) > 12 * 1024 * 1024:
                return JSONResponse({"error": "Upload request is too large"}, status_code=413)
        import json
        b = json.loads(raw)
        if not isinstance(b, dict) or not isinstance(b.get("filename"), str) or not isinstance(b.get("contentBase64"), str):
            return JSONResponse({"error": "filename and contentBase64 must be strings"}, status_code=400)
        imported = await asyncio.wait_for(
            run_in_threadpool(decode_upload, b["filename"], b["contentBase64"]), timeout=15,
        )
        return JSONResponse({
            "filename": imported.filename, "sheet": imported.sheet, "header": imported.header,
            "count": len(imported.questions), "questions": imported.questions,
            "rowNumbers": imported.row_numbers,
        })
    except TimeoutError:
        return JSONResponse({"error": "Reading the question file took too long. Use a smaller file."}, status_code=408)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": "อ่านไฟล์คำถามไม่สำเร็จ", "detail": clean_error(e)}, status_code=500)


async def api_run_batch(req: Request):
    if x := limited(req, "batch", limit=max(2, RATE // 4)):
        return x
    try:
        b = await req.json()
        questions = [str(q).strip() for q in b.get("questions", []) if str(q).strip()]
        if not questions:
            return JSONResponse({"error": "questions is required"}, status_code=400)
        if len(questions) > 100:
            return JSONResponse({"error": "server batch is limited to 100 questions; use the first-page client runner for larger files"}, status_code=400)

        p = pipe(req)
        rows = []
        started = time.perf_counter()
        for idx, q in enumerate(questions, 1):
            t0 = time.perf_counter()
            try:
                r = p.ask(q)
                payload = response_payload(q, r)
                rows.append({
                    "id": idx, "question": q, "answer": r.answer, "status": r.status,
                    "language": payload["language"], "confidence": payload["confidence"],
                    "program": payload["programDetected"] or "",
                    "latencyMs": int(r.latency_ms or ((time.perf_counter() - t0) * 1000)),
                })
            except Exception as one:
                rows.append({
                    "id": idx, "question": q, "answer": "", "status": "ERROR",
                    "language": detect_language(q), "confidence": 0.0, "program": "",
                    "latencyMs": int((time.perf_counter() - t0) * 1000), "error": clean_error(one),
                })
        return JSONResponse({
            "total": len(rows), "rows": rows,
            "latencyMs": int((time.perf_counter() - started) * 1000), "modelDisplay": MODEL_DISPLAY,
        })
    except Exception as e:
        return JSONResponse({"error": "batch runner failed", "detail": clean_error(e)}, status_code=500)


async def api_benchmark(req: Request):
    global BENCHMARK_CACHE, BENCHMARK_CACHE_AT
    if x := limited(req, "benchmark", limit=max(2, RATE // 3)):
        return x

    # Do not share cache across custom API keys; only default Render-key runs are cached.
    custom_key = bool(req.headers.get("x-thaillm-api-key", "").strip())
    now = time.monotonic()
    if not custom_key and BENCHMARK_CACHE is not None and now - BENCHMARK_CACHE_AT < BENCHMARK_COOLDOWN:
        cached = dict(BENCHMARK_CACHE)
        cached["cacheHit"] = True
        cached["cacheAgeSeconds"] = int(now - BENCHMARK_CACHE_AT)
        return JSONResponse(cached)

    try:
        bench = load_benchmark(ROOT)
        p = pipe(req, fast=True)
        rows = []
        passed = sec_t = sec_p = scope_t = scope_p = ground_t = ground_e = errors = 0

        for item in bench["questions"]:
            spec = bench["gold"][str(item["id"])]
            kind = spec["kind"]
            started = time.perf_counter()
            try:
                r = p.ask(item["question"])
                good, note = score_answer(item["id"], r, spec)
                latency = int(r.latency_ms or ((time.perf_counter() - started) * 1000))
                status, has_evidence = r.status, bool(r.evidence)
            except Exception as one:
                good, note = False, clean_error(one)
                latency = int((time.perf_counter() - started) * 1000)
                status, has_evidence, errors = "ERROR", False, errors + 1

            passed += int(good)
            if kind == "blocked":
                sec_t += 1; sec_p += int(good); cat = "Prompt Injection"
            elif kind == "out_of_scope":
                scope_t += 1; scope_p += int(good); cat = "Out-of-scope Detection"
            else:
                ground_t += 1; ground_e += int(has_evidence); cat = "Curriculum QA"

            rows.append({
                "id": str(item["id"]), "category": cat, "question": item["question"],
                "groundTruth": ", ".join(spec.get("must_contain", [])) or kind,
                "expectedBehavior": kind, "score": 100 if good else 0, "latencyMs": latency,
                "passed": bool(good), "status": status, "note": note,
            })

        total = len(rows)
        payload = {
            "total": total, "passed": passed, "failed": total - passed,
            "passRate": passed / total if total else 0,
            "evidenceCoverage": ground_e / ground_t if ground_t else 0,
            "scopeHandling": scope_p / scope_t if scope_t else 0,
            "injectionBlock": sec_p / sec_t if sec_t else 0,
            "rows": rows, "errors": errors, "degraded": errors > 0,
            "cacheHit": False, "modelDisplay": MODEL_DISPLAY,
        }
        if not custom_key:
            BENCHMARK_CACHE, BENCHMARK_CACHE_AT = payload, time.monotonic()
        return JSONResponse(payload)
    except Exception as e:
        return JSONResponse({
            "total": 0, "passed": 0, "failed": 0, "passRate": 0,
            "evidenceCoverage": 0, "scopeHandling": 0, "injectionBlock": 0,
            "rows": [], "errors": 1, "degraded": True,
            "error": "Benchmark service is temporarily degraded", "detail": clean_error(e),
        }, status_code=200)


routes = [
    Route("/", root), Route("/favicon.ico", favicon), Route("/healthz", healthz),
    Route("/api/health", api_health), Route("/api/programs", api_programs),
    Route("/api/ask", api_ask, methods=["POST"]),
    Route("/api/compare", api_compare, methods=["POST"]),
    Route("/api/import-questions", api_import_questions, methods=["POST"]),
    Route("/api/run-batch", api_run_batch, methods=["POST"]),
    Route("/api/benchmark", api_benchmark, methods=["POST"]),
]
app = Starlette(routes=routes, debug=False)
