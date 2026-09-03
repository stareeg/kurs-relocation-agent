from core.domains.pipeline import hr_import
from core.domains.pipeline.hr_import import (
    DumpMessage,
    ParsedDump,
    SplitReplica,
    dedupe_against_existing,
    split_correspondence,
)
from core.kernel import ports
from tests.fakes import FakeLlm


def _r(kind: str, body: str) -> SplitReplica:
    return SplitReplica(kind=kind, body=body)


def test_dedupe_internal_repeats_collapses_duplicated_block():
    """Реальный кейс (тред «Криптолудка»): один LLM-ответ задвоил блок из 8 реплик подряд."""
    block = [_r("hr_in" if i % 2 == 0 else "hr_out", f"Реплика {i}") for i in range(8)]
    parsed = block + block + [_r("hr_in", "Финал")]
    assert hr_import._dedupe_internal_repeats(parsed) == [*block, _r("hr_in", "Финал")]


def test_dedupe_internal_repeats_collapses_single_consecutive_duplicate():
    parsed = [_r("hr_in", "Привет"), _r("hr_in", "Привет"), _r("hr_out", "Ок")]
    assert hr_import._dedupe_internal_repeats(parsed) == [
        _r("hr_in", "Привет"),
        _r("hr_out", "Ок"),
    ]


def test_dedupe_internal_repeats_no_duplicates_untouched():
    parsed = [_r("hr_in", "A"), _r("hr_out", "B"), _r("hr_in", "C")]
    assert hr_import._dedupe_internal_repeats(parsed) == parsed


def test_dedupe_internal_repeats_ignores_case_and_whitespace():
    parsed = [_r("hr_in", "Привет   "), _r("hr_in", "  привет"), _r("hr_out", "Ок")]
    assert hr_import._dedupe_internal_repeats(parsed) == [
        _r("hr_in", "Привет   "),
        _r("hr_out", "Ок"),
    ]


async def test_split_correspondence_collapses_duplicated_prefix():
    """Плановый regression-тест: LLM вернула список с повторяющимся префиксом целиком."""
    block = [DumpMessage(sender="hr", body=f"Реплика {i}") for i in range(4)]
    parsed_dump = ParsedDump(messages=[*block, *block, DumpMessage(sender="me", body="Финал")])
    llm = FakeLlm(result=parsed_dump)
    with ports.use_ports(llm=llm):
        result = await split_correspondence("любая переписка одним куском", account_id=1)
    assert [p.body for p in result.pairs] == [
        "Реплика 0",
        "Реплика 1",
        "Реплика 2",
        "Реплика 3",
        "Финал",
    ]


def test_dedupe_prefix_overlap():
    existing = [("hr_in", "Привет"), ("hr_out", "Добрый день")]
    parsed = [_r("hr_in", "Привет"), _r("hr_out", "Добрый день"), _r("hr_in", "Когда созвон?")]
    assert dedupe_against_existing(existing, parsed) == [_r("hr_in", "Когда созвон?")]


def test_dedupe_exact_tail_match():
    existing = [("hr_in", "Старое")]
    parsed = [_r("hr_in", "Старое"), _r("hr_out", "Новое")]
    assert dedupe_against_existing(existing, parsed) == [_r("hr_out", "Новое")]


def test_dedupe_all_new():
    existing = [("hr_in", "A")]
    parsed = [_r("hr_out", "B"), _r("hr_in", "C")]
    assert dedupe_against_existing(existing, parsed) == parsed


def test_dedupe_empty_existing():
    parsed = [_r("hr_in", "X")]
    assert dedupe_against_existing([], parsed) == parsed
