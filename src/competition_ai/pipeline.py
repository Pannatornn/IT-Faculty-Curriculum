from __future__ import annotations
import os; from pathlib import Path
import time
import re

from .config import Settings
from .models import (
    Evidence,
    AnswerResult,
    Verification,
    QueryPlan,
)
from .security import (
    is_prompt_injection,
    looks_out_of_scope,
)
from .router import route_question
from .retrieval import retrieve
from .llm import ThaiLLMClient
from .cache import DiskCache
from .telemetry import Telemetry


# Bump this when retrieval/rerank behavior changes so stale cached answers
# from older pipeline versions are not reused accidentally.
PIPELINE_CACHE_VERSION = "rerank-protected-v2"


BLOCKED_TEXT = (
    "คำขอนี้พยายามเปลี่ยนหรือเปิดเผย"
    "คำสั่งภายในระบบ จึงไม่ดำเนินการต่อ "
    "แต่สามารถถามข้อมูลเกี่ยวกับหลักสูตร"
    "ของคณะเทคโนโลยีสารสนเทศ สจล. ได้"
)

OOS_TEXT = (
    "คำถามนี้อยู่นอกขอบเขตชุดข้อมูล"
    "ที่ผู้จัดกำหนด ระบบจึงไม่สร้างคำตอบ"
    "จากความรู้ภายนอก"
)

AMBIG_TEXT = (
    "คำถามนี้ยังไม่ระบุหลักสูตร "
    "กรุณาเลือก AIT, DSBA, IT หรือ IT Inter "
    "เพื่อป้องกันการตอบข้ามหลักสูตร"
)


def render_evidence(items: list[Evidence]) -> str:
    blocks = []

    for i, e in enumerate(items, 1):
        blocks.append(
            f"[E{i}] ID={e.id}\n"
            f"SOURCE={e.citation}\n"
            f"PROGRAM={e.program}\n"
            f"KIND={e.kind}\n"
            f"RETRIEVAL_SCORE={e.score}\n"
            f"TEXT:\n{e.text}"
        )

    return "\n\n---\n\n".join(blocks)


def balance_evidence_by_program(
    ranked: list[Evidence],
    programs: list[str],
    limit: int,
) -> list[Evidence]:
    """
    Comparison safety:
    guarantee representation from every selected program
    before filling remaining slots by rank.
    """
    if len(programs) <= 1:
        return ranked[:limit]

    selected: list[Evidence] = []
    seen_ids: set[str] = set()

    per_program = 2 if limit >= len(programs) * 2 else 1

    for program in programs:
        count = 0

        for item in ranked:
            if item.program == program and item.id not in seen_ids:
                selected.append(item)
                seen_ids.add(item.id)
                count += 1

                if count >= per_program:
                    break

    for item in ranked:
        if len(selected) >= limit:
            break

        if item.id not in seen_ids:
            selected.append(item)
            seen_ids.add(item.id)

    return selected[:limit]



def normalize_comparison_labels(answer: str) -> str:
    """
    Normalize only the first-column row label of Markdown comparison tables.
    Do not globally replace curriculum terminology inside the content cells.
    """
    if not answer:
        return answer

    patterns = (
        r"(?m)^(\s*\|\s*)(?:\*\*)?\s*รายวิชาแกน\s*(?:\*\*)?\s*(\|)",
        r"(?m)^(\s*\|\s*)(?:\*\*)?\s*วิชาแกน\s*(?:\*\*)?\s*(\|)",
    )

    replacement = (
        r"\1**รายวิชาพื้นฐาน/วิชาหลักของหลักสูตร**\2"
    )

    for pattern in patterns:
        answer = re.sub(pattern, replacement, answer)

    return answer

class CompetitionPipeline:
    def __init__(
        self,
        settings: Settings,
        catalog: dict,
        evidence: list[Evidence],
    ):
        self.s = settings
        self.catalog = catalog
        self.evidence = evidence;        self.llm = ThaiLLMClient(settings)

        import re; import os; from pathlib import Path
        runtime_root = Path(os.getenv("THAILLM_RUNTIME_DIR") or ("/tmp/it-faculty-curriculum" if os.getenv("VERCEL") else settings.root))

        self.cache = DiskCache(
            runtime_root,
            settings.cache_ttl,
        )

        self.telemetry = Telemetry(
            runtime_root
        )

    def _plan(
        self,
        question: str,
    ) -> QueryPlan:
        if not self.s.use_query_planner:
            return QueryPlan()

        system = (
            self.s.root
            / "prompts/query_planner.txt"
        ).read_text(
            encoding="utf-8"
        )

        data, _ = self.llm.generate_json(
            system,
            f"QUESTION:\n{question}",
        )

        return QueryPlan(
            intent=str(
                data.get(
                    "intent",
                    "unknown",
                )
            ),
            keywords=list(
                data.get(
                    "keywords",
                    [],
                )
            ),
            subjective=bool(
                data.get(
                    "subjective",
                    False,
                )
            ),
            needs_comparison=bool(
                data.get(
                    "needs_comparison",
                    False,
                )
            ),
            requires_exact_number=bool(
                data.get(
                    "requires_exact_number",
                    False,
                )
            ),
            needs_course_lookup=bool(
                data.get(
                    "needs_course_lookup",
                    False,
                )
            ),
            language=str(
                data.get(
                    "language",
                    "th",
                )
            ),
        )

    def _rerank(
        self,
        question: str,
        candidates: list[Evidence],
    ) -> list[Evidence]:
        """
        LLM rerank with deterministic protection for canonical facts.

        retrieve() marks topic-matched canonical facts with very high scores
        (normally 10000). Those facts are source-grounded and must not be
        dropped simply because the LLM omits their IDs from its JSON output.
        """
        if not candidates:
            return []

        system = (
            self.s.root
            / "prompts/rerank.txt"
        ).read_text(
            encoding="utf-8"
        )

        data, _ = self.llm.generate_json(
            system,
            f"QUESTION:\n{question}\n\n"
            f"CANDIDATES:\n"
            f"{render_evidence(candidates)}",
        )

        score_map: dict[str, float] = {}

        for item in data.get("ranked", []):
            try:
                cid = str(item.get("id", ""))
                score = float(item.get("score", 0))
            except Exception:
                continue

            if cid:
                score_map[cid] = score

        llm_ranked: list[Evidence] = []

        for e in candidates:
            if e.id in score_map:
                llm_ranked.append(
                    Evidence(
                        **{
                            **e.__dict__,
                            "score": score_map[e.id],
                        }
                    )
                )

        llm_ranked.sort(
            key=lambda x: x.score,
            reverse=True,
        )

        # Protect high-confidence canonical evidence selected deterministically
        # by retrieval/topic matching.
        protected = [
            e
            for e in candidates
            if (
                e.kind == "canonical"
                and e.score >= 9000
            )
        ]

        protected.sort(
            key=lambda x: x.score,
            reverse=True,
        )

        protected_ids = {
            e.id
            for e in protected
        }

        # Preserve LLM ordering for non-protected items.
        merged = protected + [
            e
            for e in llm_ranked
            if e.id not in protected_ids
        ]

        # If the LLM returned no usable IDs, keep the retrieval order.
        if not merged:
            return candidates

        # Also keep omitted retrieval candidates behind the reranked list.
        # This gives downstream balancing/fallback enough evidence without
        # allowing omitted items to outrank protected facts.
        merged_ids = {e.id for e in merged}

        merged.extend(
            e
            for e in candidates
            if e.id not in merged_ids
        )

        return merged

    def compare(
        self,
        question: str,
        programs: list[str],
        focus: str,
    ) -> AnswerResult:
        """
        Dedicated comparison path:
        source-balanced evidence + comparison-specific prompt.
        """
        t0 = time.perf_counter()

        candidates = retrieve(
            question + " " + focus,
            self.evidence,
            programs,
            top_k=max(
                self.s.top_candidates,
                len(programs) * 8,
            ),
            planner_keywords=[
                "รายวิชา",
                "ทักษะ",
                focus,
            ],
        )

        ranked = candidates

        debug = {
            "comparison_mode": True,
            "rerank_fallback": False,
        }

        if self.s.use_rerank and candidates:
            try:
                ranked = self._rerank(
                    question + " " + focus,
                    candidates,
                )

            except Exception as exc:
                debug["rerank_fallback"] = True
                debug["rerank_error"] = str(exc)
                ranked = candidates

        evidence_limit = max(
            self.s.evidence_k,
            len(programs) * 3,
        )

        final_evidence = balance_evidence_by_program(
            ranked,
            programs,
            evidence_limit,
        )

        if not final_evidence:
            return AnswerResult(
                status="NO_EVIDENCE",
                answer="ไม่พบหลักฐานเพียงพอสำหรับการเปรียบเทียบ",
                programs=programs,
                debug=debug,
            )

        system = (
            self.s.root
            / "prompts/compare.txt"
        ).read_text(
            encoding="utf-8"
        )

        answer = self.llm.generate(
            system,
            f"PROGRAMS: {programs}\n"
            f"FOCUS: {focus}\n"
            f"QUESTION: {question}\n\n"
            f"EVIDENCE:\n"
            f"{render_evidence(final_evidence)}",
        )

        # Normalize only the shared comparison-table row label.
        answer = normalize_comparison_labels(answer)

        verification = None

        if self.s.verify_answers:
            try:
                verification = self._verify(
                    question + " | focus=" + focus,
                    answer,
                    final_evidence,
                )

            except Exception as exc:
                verification = Verification(
                    status="CHECK_REQUIRED",
                    confidence=0.0,
                    rationale=(
                        "Verifier unavailable: "
                        f"{exc}"
                    ),
                )

        latency_ms = int(
            (
                time.perf_counter()
                - t0
            )
            * 1000
        )

        return AnswerResult(
            status=(
                verification.status
                if verification
                else "SUPPORTED"
            ),
            answer=answer,
            programs=programs,
            evidence=final_evidence,
            verification=verification,
            latency_ms=latency_ms,
            debug=debug,
        )

    def _answer(
        self,
        question: str,
        evidence: list[Evidence],
    ) -> str:
        system = (
            self.s.root
            / "prompts/answer.txt"
        ).read_text(
            encoding="utf-8"
        )

        return self.llm.generate(
            system,
            f"QUESTION:\n{question}\n\n"
            f"EVIDENCE:\n"
            f"{render_evidence(evidence)}",
        )

    def _verify(
        self,
        question: str,
        answer: str,
        evidence: list[Evidence],
    ) -> Verification:
        system = (
            self.s.root
            / "prompts/verify.txt"
        ).read_text(
            encoding="utf-8"
        )

        data, _ = self.llm.generate_json(
            system,
            f"QUESTION:\n{question}\n\n"
            f"ANSWER:\n{answer}\n\n"
            f"EVIDENCE:\n"
            f"{render_evidence(evidence)}",
        )

        try:
            confidence = max(
                0.0,
                min(
                    float(
                        data.get(
                            "confidence",
                            0,
                        )
                    ),
                    1.0,
                ),
            )
        except Exception:
            confidence = 0.0

        return Verification(
            status=str(
                data.get(
                    "status",
                    "UNSUPPORTED",
                )
            ).upper(),
            confidence=confidence,
            rationale=str(
                data.get(
                    "rationale",
                    "",
                )
            ),
            unsupported_claims=list(
                data.get(
                    "unsupported_claims",
                    [],
                )
            ),
            supported_claims=list(
                data.get(
                    "supported_claims",
                    [],
                )
            ),
        )

    def _repair(
        self,
        question: str,
        answer: str,
        evidence: list[Evidence],
    ) -> str:
        system = (
            self.s.root
            / "prompts/repair.txt"
        ).read_text(
            encoding="utf-8"
        )

        return self.llm.generate(
            system,
            f"QUESTION:\n{question}\n\n"
            f"ANSWER_TO_REPAIR:\n"
            f"{answer}\n\n"
            f"EVIDENCE:\n"
            f"{render_evidence(evidence)}",
        )

    def ask(
        self,
        question: str,
        forced_program: str | None = None,
    ) -> AnswerResult:
        t0 = time.perf_counter()
        question = question.strip()

        if not question:
            return AnswerResult(
                status="EMPTY",
                answer="กรุณาพิมพ์คำถาม",
            )

        if is_prompt_injection(question):
            self.telemetry.log({
                "event": "blocked",
                "question": question,
            })

            return AnswerResult(
                status="BLOCKED",
                answer=BLOCKED_TEXT,
            )

        route = route_question(
            question,
            self.catalog,
            forced_program=forced_program,
        )

        if (
            not route.programs
            and looks_out_of_scope(question)
        ):
            return AnswerResult(
                status="OUT_OF_SCOPE",
                answer=OOS_TEXT,
            )

        if route.ambiguous:
            return AnswerResult(
                status="NEEDS_CONTEXT",
                answer=AMBIG_TEXT,
            )

        cache_key = (
            f"{PIPELINE_CACHE_VERSION}|"
            f"{self.s.model}|"
            f"{route.programs}|"
            f"{question}"
        )

        if self.s.enable_cache:
            cached = self.cache.get(
                cache_key
            )

            if cached:
                return AnswerResult(
                    status=cached["status"],
                    answer=cached["answer"],
                    programs=cached["programs"],
                    evidence=[
                        Evidence(**x)
                        for x in cached["evidence"]
                    ],
                    verification=(
                        Verification(
                            **cached["verification"]
                        )
                        if cached.get(
                            "verification"
                        )
                        else None
                    ),
                    plan=(
                        QueryPlan(
                            **cached["plan"]
                        )
                        if cached.get(
                            "plan"
                        )
                        else None
                    ),
                    latency_ms=0,
                    cache_hit=True,
                )

        debug = {
            "route": route.__dict__,
            "rerank_fallback": False,
            "planner_fallback": False,
            "repair_used": False,
        }

        try:
            plan = self._plan(
                question
            )

        except Exception as exc:
            plan = QueryPlan()
            debug["planner_fallback"] = True
            debug["planner_error"] = str(exc)

        candidates = retrieve(
            question,
            self.evidence,
            route.programs,
            top_k=self.s.top_candidates,
            planner_keywords=plan.keywords,
        )

        debug["candidate_ids"] = [
            e.id for e in candidates
        ]

        debug["protected_candidate_ids"] = [
            e.id
            for e in candidates
            if (
                e.kind == "canonical"
                and e.score >= 9000
            )
        ]

        ranked = candidates

        if (
            self.s.use_rerank
            and candidates
        ):
            try:
                ranked = self._rerank(
                    question,
                    candidates,
                )

            except Exception as exc:
                debug["rerank_fallback"] = True
                debug["rerank_error"] = str(exc)
                ranked = candidates

        final_evidence = balance_evidence_by_program(
            ranked,
            route.programs,
            self.s.evidence_k,
        )

        debug["final_evidence_ids"] = [
            e.id
            for e in final_evidence
        ]

        if not final_evidence:
            return AnswerResult(
                status="NO_EVIDENCE",
                answer=(
                    "ไม่พบหลักฐานที่เกี่ยวข้อง"
                    "ในชุดข้อมูล"
                ),
                programs=route.programs,
                plan=plan,
                debug=debug,
            )

        try:
            answer = self._answer(
                question,
                final_evidence,
            )

        except Exception as exc:
            return AnswerResult(
                status="API_ERROR",
                answer=(
                    "ThaiLLM ไม่สามารถสร้าง"
                    "คำตอบได้ในขณะนี้: "
                    f"{exc}"
                ),
                programs=route.programs,
                evidence=final_evidence,
                plan=plan,
                debug=debug,
            )

        verification = None

        if self.s.verify_answers:
            try:
                verification = self._verify(
                    question,
                    answer,
                    final_evidence,
                )

                if (
                    self.s.answer_repair
                    and verification.status
                    == "PARTIALLY_SUPPORTED"
                ):
                    repaired = self._repair(
                        question,
                        answer,
                        final_evidence,
                    )

                    second = self._verify(
                        question,
                        repaired,
                        final_evidence,
                    )

                    if second.status == "SUPPORTED":
                        answer = repaired
                        verification = second
                        debug["repair_used"] = True

            except Exception as exc:
                verification = Verification(
                    status="CHECK_REQUIRED",
                    confidence=0.0,
                    rationale=(
                        "Verifier unavailable: "
                        f"{exc}"
                    ),
                )
                debug["verification_error"] = str(exc)

        if (
            verification
            and verification.status
            == "UNSUPPORTED"
        ):
            answer = (
                "หลักฐานที่ค้นพบยังไม่เพียงพอ"
                "สำหรับยืนยันคำตอบ จึงไม่ควรเดา"
                "\n\nเหตุผล: "
                + verification.rationale
            )

        status = (
            verification.status
            if verification
            else "SUPPORTED"
        )

        latency_ms = int(
            (
                time.perf_counter()
                - t0
            )
            * 1000
        )

        result = AnswerResult(
            status=status,
            answer=answer,
            programs=route.programs,
            evidence=final_evidence,
            verification=verification,
            plan=plan,
            latency_ms=latency_ms,
            debug=debug,
        )

        if self.s.enable_cache:
            self.cache.set(
                cache_key,
                {
                    "status": result.status,
                    "answer": result.answer,
                    "programs": result.programs,
                    "evidence": [
                        e.__dict__
                        for e in result.evidence
                    ],
                    "verification": (
                        result.verification.__dict__
                        if result.verification
                        else None
                    ),
                    "plan": (
                        result.plan.__dict__
                        if result.plan
                        else None
                    ),
                },
            )

        self.telemetry.log({
            "event": "answer",
            "question": question,
            "programs": route.programs,
            "status": result.status,
            "latency_ms": latency_ms,
            "rerank_fallback": debug[
                "rerank_fallback"
            ],
            "repair_used": debug[
                "repair_used"
            ],
        })

        return result
