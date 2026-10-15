from pathlib import Path

import pytest

from competition_ai.router import load_catalog, route_question

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
