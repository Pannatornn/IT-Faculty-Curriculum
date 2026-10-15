from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from competition_ai.config import SETTINGS
from competition_ai.knowledge import load_catalog, load_evidence
from competition_ai.models import AnswerResult, Evidence
from competition_ai.pipeline import CompetitionPipeline
from competition_ai.policy import detect_language
from competition_ai.policy_pipeline import PolicyCompetitionPipeline, _chinese_basic_facts


ROOT = Path(__file__).resolve().parents[1]
CHINESE_EASY_Q3 = "KMITL信息技术学院的人工智能技术专业(AIT)总共需要修满多少学分?学制几年?"
THAI_Q3_ANSWER = "KMITL หลักสูตร AIT ต้องเรียนรวมทั้งหมด 120 หน่วยกิต และมีระยะเวลาการศึกษา 4 ปี"


def policy_with_rewrite(rewrite):
    policy = object.__new__(PolicyCompetitionPipeline)
    policy.s = replace(SETTINGS, root=ROOT)
    policy.llm = SimpleNamespace(generate=rewrite)
    return policy


def test_actual_chinese_easy_question_uses_grounded_basic_facts_if_initial_answer_is_thai():
    catalog = load_catalog(ROOT)
    evidence = [e for e in load_evidence(ROOT, catalog) if e.program == "AIT" and e.metadata.get("topic") == "basic"]
    result = AnswerResult(status="SUPPORTED", answer=THAI_Q3_ANSWER, programs=["AIT"], evidence=evidence)

    def exhausted_rewrite(*args, **kwargs):
        pytest.fail("Canonical total credits and duration must not need another upstream request")

    rewritten = policy_with_rewrite(exhausted_rewrite)._ensure_answer_language(CHINESE_EASY_Q3, result)
    assert detect_language(CHINESE_EASY_Q3) == "zh"
    assert detect_language(rewritten.answer) == "zh"
    assert "120学分" in rewritten.answer
    assert "4年" in rewritten.answer
    assert "[E1]" in rewritten.answer
    assert rewritten.status == "SUPPORTED"
    assert rewritten.debug["canonical_language_fallback"] is True


@pytest.mark.parametrize("rewrite", ["", THAI_Q3_ANSWER])
def test_blank_or_wrong_language_rewrite_becomes_retryable_chinese_response(rewrite):
    policy = policy_with_rewrite(lambda *args, **kwargs: rewrite)
    result = policy._ensure_answer_language(
        CHINESE_EASY_Q3, AnswerResult(status="SUPPORTED", answer=THAI_Q3_ANSWER, programs=["AIT"])
    )
    assert result.status == "RETRY_REQUIRED"
    assert detect_language(result.answer) == "zh"
    assert result.debug["language_enforced"] is False
    assert result.evidence == []


def test_rewrite_network_failure_cannot_return_thai_success_for_chinese_question():
    def failed(*args, **kwargs):
        raise RuntimeError("request budget exhausted")

    result = policy_with_rewrite(failed)._ensure_answer_language(
        CHINESE_EASY_Q3, AnswerResult(status="SUPPORTED", answer=THAI_Q3_ANSWER, programs=["AIT"])
    )
    assert result.status == "RETRY_REQUIRED"
    assert detect_language(result.answer) == "zh"
    assert result.debug["language_enforced"] is False


def test_chinese_visible_answer_ignores_translated_dump_with_thai_ocr_for_language_detection():
    def unnecessary_rewrite(*args, **kwargs):
        pytest.fail("The visible answer already matches the question's language")

    answer = "AIT课程于2023年7月开课。\n证据：\n- [E1] 课程文件第4页明确说明开课时间。"
    result = AnswerResult(
        status="SUPPORTED", programs=["AIT"],
        answer=answer + "\n\n证据：\n[E1] ID=FACT-AIT-1\n来源=AIT.pdf\n文本：\nข้อความจากเอกสารภาษาไทย",
    )
    returned = policy_with_rewrite(unnecessary_rewrite)._ensure_answer_language(
        "AIT人工智能技术专业从什么时候开始招生开课?", result
    )
    assert returned.answer == answer
    assert returned.status == "SUPPORTED"


def test_successful_language_rewrite_is_cleaned_and_verified():
    policy = policy_with_rewrite(lambda *args, **kwargs: "AIT于2023年7月开课。[E1]\n证据：\n[E1] ID=FACT-AIT-1\n来源=AIT.pdf")
    result = policy._ensure_answer_language(
        "AIT人工智能技术专业从什么时候开始招生开课?",
        AnswerResult(status="SUPPORTED", answer="AIT เปิดสอนเดือนกรกฎาคม 2566", programs=["AIT"]),
    )
    assert result.answer == "AIT于2023年7月开课。[E1]"
    assert result.debug["language_enforced"] is True


def test_canonical_basic_fallback_rejects_subcategory_or_conflicting_facts():
    evidence = [Evidence("basic", "AIT.pdf", 2, "AIT มี 120 หน่วยกิต เป็นหลักสูตร 4 ปี", "AIT", kind="canonical", metadata={"topic": "basic"})]
    result = AnswerResult(status="SUPPORTED", answer=THAI_Q3_ANSWER, programs=["AIT"], evidence=evidence)
    assert _chinese_basic_facts("AIT专业课程总共需要多少学分?学制几年?", result) is None
    result.evidence.append(Evidence("conflict", "AIT.pdf", 3, "AIT มี 129 หน่วยกิต เป็นหลักสูตร 4 ปี", "AIT", kind="canonical", metadata={"topic": "basic"}))
    assert _chinese_basic_facts(CHINESE_EASY_Q3, result) is None


def test_answer_writer_explicitly_receives_chinese_language_and_dump_prohibition():
    captured = {}

    def generate(system, question, **kwargs):
        captured["system"] = system
        return "AIT课程共需修满120学分，学制为4年。"

    pipeline = object.__new__(CompetitionPipeline)
    pipeline.s = replace(SETTINGS, root=ROOT)
    pipeline.llm = SimpleNamespace(generate=generate)
    assert detect_language(pipeline._answer(CHINESE_EASY_Q3, [])) == "zh"
    assert "Required answer language: Simplified Chinese" in captured["system"]
    assert "Never copy retrieval entries" in captured["system"]
