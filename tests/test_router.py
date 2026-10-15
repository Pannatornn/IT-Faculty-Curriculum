from pathlib import Path

import pytest

from competition_ai.router import detect_programs, load_catalog, route_question

ROOT = Path(__file__).resolve().parents[1]
CAT = load_catalog(ROOT/"knowledge/program_catalog.json")

def test_ait_route():
    assert route_question("AIT เรียนกี่หน่วยกิต", CAT).programs == ["AIT"]

def test_it_inter_not_plain_it():
    r = route_question("IT Inter เรียนภาษาอะไร", CAT)
    assert r.programs == ["IT_INTER"]

def test_ambiguous_short_query():
    assert route_question("เรียนกี่หน่วยกิต", CAT).ambiguous is True

def test_compare_two():
    r = route_question("เปรียบเทียบ AIT กับ DSBA", CAT)
    assert set(r.programs) == {"AIT","DSBA"}


def test_compare_ait_it():
    r = route_question("เปรียบเทียบจำนวนหน่วยกิต AIT กับ IT", CAT)
    assert set(r.programs) == {"AIT","IT"}


@pytest.mark.parametrize(
    "question",
    [
        "Compare IT and IT International credits",
        "Compare IT International and IT credits",
        "IT2565 vs IT_INTER",
        "IT 2565 กับ IT-International ต่างกันอย่างไร",
    ],
)
def test_plain_it_remains_in_comparison_with_international(question):
    route = route_question(question, CAT)
    assert set(route.programs) == {"IT", "IT_INTER"}
    assert route.comparison


@pytest.mark.parametrize("name", ["IT Inter", "IT International", "IT_INTER", "IT-International"])
def test_international_alias_alone_does_not_create_plain_it(name):
    assert route_question(f"{name} credits", CAT).programs == ["IT_INTER"]


EASY_FIRST_QUESTION = (
    "หลักสูตรวิทยาศาสตรบัณฑิต สาขาวิชาเทคโนโลยีปัญญาประดิษฐ์ (AIT) "
    "คณะเทคโนโลยีสารสนเทศ สจล. ใช้เวลาเรียนกี่หน่วยกิตตลอดหลักสูตร และเป็นหลักสูตรกี่ปี"
)


def test_easy_first_question_selects_ait_degree_without_faculty_it_alias():
    route = route_question(EASY_FIRST_QUESTION, CAT)
    assert route.programs == ["AIT"]
    assert route.comparison is False


@pytest.mark.parametrize(
    "faculty",
    [
        "คณะเทคโนโลยีสารสนเทศ สจล.",
        "คณะ เทคโนโลยีสารสนเทศ (IT)",
        "คณะ IT (Information Technology)",
        "KMITL School of Information Technology",
        "Faculty of Information Technology (IT)",
        "School of IT",
        "Information Technology Faculty",
        "IT School",
        "信息技术学院",
        "信息技术（IT）学院",
        "資訊科技學院 (IT)",
        "IT学院",
    ],
)
def test_faculty_mentions_do_not_add_it_to_another_degree(faculty):
    assert detect_programs(f"AIT / {faculty}: curriculum credits?", CAT) == ["AIT"]
    assert detect_programs(f"DSBA / {faculty}: curriculum credits?", CAT) == ["DSBA"]
    assert detect_programs(f"IT International / {faculty}: curriculum credits?", CAT) == ["IT_INTER"]


@pytest.mark.parametrize(
    "faculty", ["คณะเทคโนโลยีสารสนเทศ", "School of Information Technology (IT)", "信息技术（IT）学院"]
)
def test_faculty_name_without_a_degree_does_not_select_it(faculty):
    assert detect_programs(f"{faculty} offers which programs?", CAT) == []


@pytest.mark.parametrize(
    "question",
    [
        "หลักสูตร IT ของคณะเทคโนโลยีสารสนเทศมีกี่หน่วยกิต",
        "สาขาวิชาเทคโนโลยีสารสนเทศ คณะเทคโนโลยีสารสนเทศมีกี่หน่วยกิต",
        "IT KMITL curriculum credits?",
        "The IT program at the School of Information Technology",
        "Bachelor of Science Program in Information Technology, Faculty of Information Technology",
    ],
)
def test_explicit_it_degree_remains_after_faculty_name_is_removed(question):
    assert detect_programs(question, CAT) == ["IT"]


def test_all_explicit_degree_names_remain_with_faculty_name():
    route = route_question(
        "Compare AIT, DSBA, IT and IT International in the KMITL School of Information Technology.", CAT
    )
    assert set(route.programs) == {"AIT", "DSBA", "IT", "IT_INTER"}
    assert route.comparison is True
