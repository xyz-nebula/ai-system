import json

from arena_ai.metrics_report import main

COLLEGES = ("hiring", "negotiation", "ownership")


def slot(
    name,
    status="ready",
    *,
    error_code=None,
    duration_ms=1000,
    model_calls=1,
    redrafts=0,
    tokens=(100, 10),
    quotes=(1, 0, 0, 0),
    **codes,
):
    return {
        "slot": name,
        "status": status,
        "error_code": error_code,
        "duration_ms": duration_ms,
        "model_calls": model_calls,
        "redrafts": redrafts,
        "input_tokens": tokens[0] if tokens else None,
        "output_tokens": tokens[1] if tokens else None,
        "calls_without_usage": 0 if tokens else model_calls,
        "quotes": dict(zip(("exact", "moved", "substituted", "dropped"), quotes, strict=True)),
        **codes,
    }


def evaluation(recorded_at, duration_ms, slots):
    return {
        "event": "evaluation",
        "evaluation_id": recorded_at,
        "recorded_at": recorded_at,
        "duration_ms": duration_ms,
        "validation": "soft",
        "model": "qwen3.8-9b-q4",
        "corpus_version": "2026-09-29.2",
        "messages": 6,
        "user_messages": 3,
        "preparation": True,
        "slots": slots,
    }


# Three hand-written evaluations; every expected figure below is worked out from them.
A = evaluation(
    "2026-10-20T10:00:00+00:00",
    40000,
    [
        slot(
            "outcome", duration_ms=8000, tokens=(1000, 200), quotes=(2, 0, 0, 0), kind="agreement"
        ),
        slot(
            "hiring",
            duration_ms=10000,
            tokens=(2000, 300),
            choice="ai",
            decisive_criterion="Надёжность",
        ),
        slot(
            "negotiation",
            duration_ms=10000,
            tokens=(2000, 300),
            quotes=(0, 1, 0, 0),
            choice="ai",
            decisive_criterion="Движение к цели",
        ),
        slot(
            "ownership",
            duration_ms=10000,
            tokens=(2000, 300),
            quotes=(0, 0, 1, 0),
            choice="ai",
            decisive_criterion="Качество решений",
        ),
        slot(
            "trainer",
            duration_ms=2000,
            model_calls=2,
            redrafts=1,
            tokens=(3000, 900),
            quotes=(3, 0, 0, 1),
        ),
    ],
)
B = evaluation(
    "2026-10-20T11:00:00+00:00",
    20000,
    [
        slot("outcome", duration_ms=4000, tokens=(500, 100), kind="no_agreement"),
        slot(
            "hiring",
            duration_ms=5000,
            tokens=(1000, 100),
            choice="user",
            decisive_criterion="Ответственность",
        ),
        slot(
            "negotiation",
            duration_ms=5000,
            tokens=(1000, 100),
            choice="ai",
            decisive_criterion="Движение к цели",
        ),
        slot(
            "ownership",
            "failed",
            error_code="invalid_judge_output",
            duration_ms=5000,
            model_calls=2,
            redrafts=1,
            tokens=None,
            quotes=(0, 0, 0, 0),
            choice=None,
            decisive_criterion=None,
        ),
        slot("trainer", duration_ms=1000, tokens=(1500, 300), quotes=(3, 0, 0, 0)),
    ],
)
C = evaluation(
    "2026-10-21T09:00:00+00:00",
    60000,
    [
        slot(
            "outcome",
            "failed",
            error_code="outcome_analysis_unavailable",
            duration_ms=30000,
            tokens=None,
            quotes=(0, 0, 0, 0),
            kind=None,
        ),
        slot(
            "hiring",
            duration_ms=10000,
            tokens=(1000, 100),
            choice="user",
            decisive_criterion="Надёжность",
        ),
        slot(
            "negotiation",
            duration_ms=10000,
            tokens=(1000, 100),
            choice="ai",
            decisive_criterion="Движение к цели",
        ),
        slot(
            "ownership",
            duration_ms=10000,
            tokens=(1000, 100),
            choice="user",
            decisive_criterion="Качество решений",
        ),
        slot("trainer", duration_ms=10000, tokens=(2000, 400)),
    ],
)


def summarize(tmp_path, capsys, lines, *arguments):
    path = tmp_path / "evaluations.jsonl"
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    main(["--file", str(path), *arguments])
    return json.loads(capsys.readouterr().out)


def records(*values):
    return [json.dumps(value, ensure_ascii=False) for value in values]


def test_summary_reports_volume_and_slot_reliability(tmp_path, capsys):
    summary = summarize(tmp_path, capsys, records(A, B, C))

    assert summary["evaluations"] == 3
    assert summary["period"] == {"first": A["recorded_at"], "last": C["recorded_at"]}
    reliability = {
        name: (slot["ready_share"], slot["error_codes"], slot["redraft_share"])
        for name, slot in summary["slots"].items()
    }
    assert reliability == {
        "outcome": (0.667, {"outcome_analysis_unavailable": 1}, 0.0),
        "hiring": (1.0, {}, 0.0),
        "negotiation": (1.0, {}, 0.0),
        "ownership": (0.667, {"invalid_judge_output": 1}, 0.333),
        "trainer": (1.0, {}, 0.333),
    }


def test_summary_reports_duration_median_p95_and_max(tmp_path, capsys):
    summary = summarize(tmp_path, capsys, records(A, B, C))

    # nearest-rank p95 of three evaluations is the slowest one
    assert summary["duration_ms"] == {"median": 40000, "p95": 60000, "max": 60000}
    assert {name: slot["duration_ms_median"] for name, slot in summary["slots"].items()} == {
        "outcome": 8000,
        "hiring": 10000,
        "negotiation": 10000,
        "ownership": 10000,
        "trainer": 2000,
    }


def test_summary_reports_tokens_and_flags_calls_without_usage(tmp_path, capsys):
    summary = summarize(tmp_path, capsys, records(A, B, C))

    # A: 10000 + 2000; B: 4000 + 600 known; C: 5000 + 700 known
    assert summary["tokens_per_evaluation"] == {
        "input_mean": 6333.3,
        "output_mean": 1100.0,
        "total_mean": 7433.3,
        "total_median": 5700,
        "complete": False,
        "calls_without_usage": 3,
    }
    # Per-evaluation slot means add up to the evaluation mean.
    assert {name: slot["tokens_mean"] for name, slot in summary["slots"].items()} == {
        "outcome": {"input": 500.0, "output": 100.0},
        "hiring": {"input": 1333.3, "output": 166.7},
        "negotiation": {"input": 1333.3, "output": 166.7},
        "ownership": {"input": 1000.0, "output": 133.3},
        "trainer": {"input": 2166.7, "output": 533.3},
    }


def test_summary_reports_quote_binding_of_ready_slots(tmp_path, capsys):
    summary = summarize(tmp_path, capsys, records(A, B, C))

    # exact 6 + 6 + 4, one moved and one substituted in A; failed slots do not count
    assert summary["quotes"] == {
        "total": 18,
        "exact": 0.889,
        "moved": 0.056,
        "substituted": 0.056,
        "dropped": 0.056,
    }


def test_summary_reports_judge_choices_agreement_and_outcomes(tmp_path, capsys):
    summary = summarize(tmp_path, capsys, records(A, B, C))

    assert summary["judges"] == {
        # A: ai ai ai; B: user ai (ownership failed); C: user ai user
        "ai_choice_share": 0.625,
        "ai_choice_share_by_college": {"hiring": 0.333, "negotiation": 1.0, "ownership": 0.5},
        # only A and C have three ready judges, and only A is unanimous
        "unanimous_share": 0.5,
        "unanimous_base": 2,
        "decisive_criteria": {
            "hiring": {"Надёжность": 2, "Ответственность": 1},
            "negotiation": {"Движение к цели": 3},
            "ownership": {"Качество решений": 2},
        },
    }
    assert summary["outcomes"] == {"agreement": 1, "no_agreement": 1}


def test_summary_window_and_unreadable_lines(tmp_path, capsys):
    # A half-written last line, e.g. after a crash mid-append, is skipped and counted.
    lines = [*records(A, B, C), '{"event": "evaluation", "recor']
    since, until = "2026-10-20T10:30:00+00:00", "2026-10-21"

    summary = summarize(tmp_path, capsys, lines, "--since", since, "--until", until)

    # A date without a time is midnight UTC, so C (09:00 on the 21st) is outside.
    assert summary["evaluations"] == 1
    assert summary["period"] == {"first": B["recorded_at"], "last": B["recorded_at"]}
    assert summary["skipped_lines"] == 1


def test_summary_of_an_empty_file_has_no_figures(tmp_path, capsys):
    summary = summarize(tmp_path, capsys, [])

    assert (summary["evaluations"], summary["skipped_lines"]) == (0, 0)
    assert summary["duration_ms"] == {"median": None, "p95": None, "max": None}
    assert summary["tokens_per_evaluation"]["total_mean"] is None
    assert summary["slots"]["outcome"]["ready_share"] is None
    assert summary["judges"]["ai_choice_share"] is None


def test_slots_without_a_model_call_do_not_pull_duration_medians_down(tmp_path, capsys):
    # One side never spoke: the judges and the trainer fail at once, without calling the model.
    silent = evaluation(
        "2026-10-21T10:00:00+00:00",
        6000,
        [
            slot("outcome", duration_ms=6000, kind="not_assessable"),
            *(
                slot(
                    name,
                    "failed",
                    error_code="insufficient_evidence",
                    duration_ms=0,
                    model_calls=0,
                    tokens=None,
                    quotes=(0, 0, 0, 0),
                    choice=None,
                    decisive_criterion=None,
                )
                for name in COLLEGES
            ),
            slot(
                "trainer",
                "failed",
                error_code="insufficient_evidence",
                duration_ms=0,
                model_calls=0,
                tokens=None,
                quotes=(0, 0, 0, 0),
            ),
        ],
    )

    summary = summarize(tmp_path, capsys, records(A, B, C, silent))

    medians = {name: slot["duration_ms_median"] for name, slot in summary["slots"].items()}
    assert (medians["hiring"], medians["trainer"]) == (10000, 2000)
    assert summary["slots"]["hiring"]["ready_share"] == 0.75


def test_summary_before_the_first_evaluation_is_empty(tmp_path, capsys):
    # A fresh volume has no file until the first evaluation appends to it.
    main(["--file", str(tmp_path / "evaluations.jsonl")])

    summary = json.loads(capsys.readouterr().out)
    assert (summary["evaluations"], summary["skipped_lines"]) == (0, 0)
