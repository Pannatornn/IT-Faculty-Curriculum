from __future__ import annotations

import asyncio
import time

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

import render_app as ui
import render_server as core
from competition_ai.batch_fallback import nonempty_error_result
from competition_ai.policy import detect_language
from competition_ai.resilient_pipeline import ResilientCompetitionPipeline


def resilient_pipe(req: Request) -> ResilientCompetitionPipeline:
    return ResilientCompetitionPipeline(
        core.request_settings(req),
        core.CATALOG,
        core.EVIDENCE,
    )


async def root(_: Request):
    return HTMLResponse(
        ui.enhanced_ui(),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def api_ask(req: Request):
    if x := core.limited(req, "ask"):
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
    if len(raw_question) > 4000:
        return JSONResponse({"error": "question is limited to 4000 characters"}, status_code=400)
    question = raw_question.strip()

    forced = body.get("program")
    forced = forced if isinstance(forced, str) and forced in {"AIT", "DSBA", "IT", "IT_INTER"} else None
    try:
        result = await asyncio.wait_for(
            run_in_threadpool(lambda: resilient_pipe(req).ask(question, forced_program=forced)),
            timeout=core.PUBLIC_QUERY_TIMEOUT_SECONDS,
        )
        return JSONResponse(core.response_payload(question, result))
    except TimeoutError:
        return JSONResponse(
            {"error": "The answer took too long. Please try again.", "type": "TIMEOUT", "retryable": True},
            status_code=504,
        )
    except Exception as exc:
        # Competition invariant: never return a blank answer for a valid row.
        fallback = nonempty_error_result(question, core.clean_error(exc))
        payload = core.response_payload(question, fallback)
        payload["degraded"] = True
        payload["degradedReason"] = "temporary processing failure; rerun recommended"
        return JSONResponse(payload, status_code=200)


async def api_run_batch(req: Request):
    if x := core.limited(req, "batch", limit=max(100, core.RATE)):
        return x

    try:
        body = await req.json()
        if not isinstance(body, dict) or not isinstance(body.get("questions"), list):
            return JSONResponse({"error": "questions must be an array of strings"}, status_code=400)
        supplied = body["questions"]
        if not supplied or any(not isinstance(q, str) or not q.strip() or len(q) > 4000 for q in supplied):
            return JSONResponse({"error": "Each question must be a non-empty string up to 4000 characters"}, status_code=400)
        if len(supplied) > 100:
            return JSONResponse({"error": "batch is limited to 100 questions"}, status_code=400)
        questions = [q.strip() for q in supplied]

        rows = []
        batch_started = time.perf_counter()

        for idx, question in enumerate(questions, 1):
            started = time.perf_counter()
            try:
                # A fresh budget per item; the UI runs one bounded item per
                # request so Stop/Resume does not restart completed questions.
                pipeline = resilient_pipe(req)
                result = await asyncio.wait_for(run_in_threadpool(pipeline.ask, question), timeout=90)
            except Exception as exc:
                result = nonempty_error_result(question, core.clean_error(exc))

            payload = core.response_payload(question, result)
            answer = str(payload["answer"] or "").strip()
            if not answer:
                result = nonempty_error_result(question, "empty answer guard")
                payload = core.response_payload(question, result)
                answer = result.answer

            rows.append({
                "id": idx,
                "question": question,
                "answer": answer,
                "status": payload["status"],
                "degraded": payload.get("degraded", False),
                "language": payload["language"] or detect_language(question),
                "confidence": payload["confidence"],
                "program": payload["programDetected"] or "",
                "latencyMs": int(
                    getattr(result, "latency_ms", 0)
                    or ((time.perf_counter() - started) * 1000)
                ),
            })

        return JSONResponse({
            "total": len(rows),
            "rows": rows,
            "latencyMs": int((time.perf_counter() - batch_started) * 1000),
            "modelDisplay": core.MODEL_DISPLAY,
            "blankAnswers": sum(1 for row in rows if not str(row["answer"]).strip()),
        })

    except ValueError:
        return JSONResponse({"error": "Invalid JSON request"}, status_code=400)
    except Exception as exc:
        return JSONResponse(
            {"error": "batch runner failed", "detail": core.clean_error(exc)},
            status_code=500,
        )


routes = [
    Route("/", root),
    Route("/favicon.ico", core.favicon),
    Route("/healthz", core.healthz),
    Route("/api/health", core.api_health),
    Route("/api/programs", core.api_programs),
    Route("/api/ask", api_ask, methods=["POST"]),
    Route("/api/compare", core.api_compare, methods=["POST"]),
    Route("/api/import-questions", core.api_import_questions, methods=["POST"]),
    Route("/api/run-batch", api_run_batch, methods=["POST"]),
    Route("/api/benchmark", core.api_benchmark, methods=["POST"]),
]

app = Starlette(routes=routes, debug=False)
