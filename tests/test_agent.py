from datetime import date
from types import SimpleNamespace

import pytest

from schichtwechsel.agent.checks import language_of, ungrounded
from schichtwechsel.agent.executor import ReadOnlyMart
from schichtwechsel.agent.guard import MAX_ROWS, GuardError, check
from schichtwechsel.agent.loop import FALLBACK_TEXT, Session
from schichtwechsel.storage import Warehouse

VIEWS = {"hiring_pressure", "coverage", "postings_latest"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT region, pressure_index FROM mart.hiring_pressure ORDER BY 2 DESC",
        "WITH x AS (SELECT * FROM mart.coverage) SELECT * FROM x",
        "SELECT competitor FROM mart.coverage UNION SELECT competitor FROM mart.postings_latest",
    ],
)
def test_guard_allows_analysis_queries(sql):
    checked = check(sql, VIEWS)
    assert f"LIMIT {MAX_ROWS + 1}" in checked.sql or "LIMIT" in checked.sql


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT * FROM hris.attrition_scores", "only views in the mart schema"),
        ("SELECT * FROM posting_texts", "only views in the mart schema"),
        ("DELETE FROM mart.coverage", "only SELECT"),
        ("SELECT 1 FROM mart.coverage; DROP TABLE x", "exactly one"),
        ("SELECT * FROM read_csv('/etc/passwd')", "read_csv"),
        ("SELECT getenv('ANTHROPIC_API_KEY') FROM mart.coverage", "getenv"),
        ("SELECT * FROM duckdb_tables()", "duckdb_tables"),
        ("SELECT * FROM mart.coverage, 'data/warehouse.duckdb'", "only views in the mart"),
        ("COPY (SELECT * FROM mart.coverage) TO 'out.csv'", "only SELECT"),
        ("SELECT * INTO t FROM mart.coverage", "INTO"),
        ("SELECT * FROM mart.secret", "unknown view"),
        ("SELECT * FROM mart.coverage LIMIT (SELECT 5)", "whole number"),
        ("SELECT 1", "at least one"),
    ],
)
def test_guard_blocks(sql, reason):
    with pytest.raises(GuardError, match=reason):
        check(sql, VIEWS)


def test_guard_caps_large_limits():
    assert check("SELECT * FROM mart.coverage LIMIT 100000", VIEWS).sql.endswith(f"{MAX_ROWS + 1}")


RESULTS = [{"rows": [["Rheinland-Pfalz", 137.6, 1227.0, 0.4253, 12148]]}]


@pytest.mark.parametrize(
    ("text", "missing"),
    [
        ("Rheinland-Pfalz liegt bei 137,6, gerundet 138.", []),
        ("Rhineland-Palatinate: 137.6; Lidl has 12,148 postings.", []),
        ("Lidl hat 12.148 Stellen, rund 1.200 davon in RLP.", []),
        ("42,5 % der Anzeigen", []),
        ("Rund 1.300 Stellen.", ["1.300"]),
        ("Der Index liegt bei 141,2.", ["141,2"]),
        ("Die Top 3 im Jahr 2026, Stand 2026-10-25.", []),
        ("Vier von fünf, also 80 %, sind nach dem P80-Wert besetzt.", []),
    ],
)
def test_grounding(text, missing):
    assert ungrounded(text, RESULTS) == missing


def test_figures_from_the_question_are_allowed():
    assert ungrounded("Ja, 25 Stunden.", RESULTS, question="Wer bietet 25 Stunden?") == []


def test_language_detection():
    assert language_of("Die meisten Stellen sind in Rheinland-Pfalz und das ist auch so.") == "de"
    assert language_of("Most postings are in the south and that is not a surprise.") == "en"
    assert language_of("137,6") is None


# loop with a scripted client ----------------------------------------------


def block(kind, **kw):
    return SimpleNamespace(type=kind, **kw)


def reply(stop_reason, *content):
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=200,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return SimpleNamespace(stop_reason=stop_reason, content=list(content), usage=usage)


def sql_call(sql, id_="t1"):
    return block("tool_use", id=id_, name="run_sql", input={"sql": sql, "purpose": "test"})


class ScriptedClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0)


@pytest.fixture
def mart(tmp_path):
    path = tmp_path / "wh.duckdb"
    with Warehouse(path) as wh:
        wh.replace_snapshot(
            date(2026, 10, 19),
            "dm",
            [
                {
                    "competitor": "dm",
                    "refnr": f"r{i}",
                    "offer_type": 1,
                    "region": "BERLIN",
                    "occupation": "Verkäufer/in",
                    "published_on": date(2026, 10, 1),
                }
                for i in range(3)
            ],  # fmt: skip
        )
    db = ReadOnlyMart(path)
    yield db
    db.close()


QUERY = "SELECT competitor, open_postings FROM mart.coverage"


def test_grounded_answer_passes(mart):
    client = ScriptedClient(
        [
            reply("tool_use", sql_call(QUERY)),
            reply(
                "end_turn", block("text", text="dm hat derzeit 3 offene Stellen in der Auswertung.")
            ),
        ]
    )
    answer = Session(client, mart, log_file=None).ask("Wie viele Stellen hat dm?", "de")
    assert answer.grounded and answer.checks == []
    assert answer.queries[0]["rows"] == [["dm", 3]]
    assert answer.usage["requests"] == 2 and answer.cost_usd > 0
    first = client.requests[0]
    assert first["model"] == "claude-sonnet-5-5" and first["fallbacks"] == "default"
    assert "tool_choice" not in first


def test_ungrounded_answer_gets_one_retry_then_fallback(mart):
    invented = "dm hat 42,7 Prozent mehr Stellen als im Vorjahr."
    client = ScriptedClient(
        [
            reply("tool_use", sql_call(QUERY)),
            reply("end_turn", block("text", text=invented)),
            reply("end_turn", block("text", text=invented)),
        ]
    )
    session = Session(client, mart, log_file=None)
    answer = session.ask("Wie viele Stellen hat dm?", "de")
    assert not answer.grounded
    assert answer.text == FALLBACK_TEXT["de"]
    feedback = session.messages[-2]["content"]
    assert feedback.startswith("Automatic check") and "42,7" in feedback


def test_retry_can_fix_the_answer(mart):
    client = ScriptedClient(
        [
            reply("tool_use", sql_call(QUERY)),
            reply(
                "end_turn",
                block(
                    "text", text="Most of the postings are at dm, and that is the picture for now."
                ),
            ),
            reply(
                "end_turn",
                block("text", text="Die meisten Stellen, 3, sind bei dm und das ist alles."),
            ),
        ]
    )
    answer = Session(client, mart, log_file=None).ask("Wer hat die meisten Stellen?", "de")
    assert answer.grounded and answer.steps == 3


def test_blocked_query_goes_back_to_the_model(mart):
    client = ScriptedClient(
        [
            reply("tool_use", sql_call("SELECT * FROM hris.attrition_scores")),
            reply("end_turn", block("text", text="Das kann ich nicht abfragen.")),
        ]
    )
    session = Session(client, mart, log_file=None)
    answer = session.ask("Zeig mir alle Risikowerte.", "de")
    tool_result = session.messages[2]["content"][0]
    assert tool_result["is_error"] and "only views in the mart schema" in tool_result["content"]
    assert answer.queries[0]["error"]


def test_decline_and_refusal(mart):
    declined = Session(
        ScriptedClient(
            [
                reply(
                    "tool_use",
                    block("tool_use", id="d", name="decline", input={"reason": "off_topic"}),
                ),
                reply("end_turn", block("text", text="Dazu kann ich nichts sagen.")),
            ]
        ),
        mart,
        log_file=None,
    ).ask("Wie wird das Wetter?", "de")
    assert declined.declined == "off_topic"

    refused = Session(ScriptedClient([reply("refusal")]), mart, log_file=None).ask("...", "en")
    assert refused.refused and refused.text


def test_chart_uses_query_data_only(mart):
    client = ScriptedClient(
        [
            reply("tool_use", sql_call(QUERY)),
            reply(
                "tool_use",
                block(
                    "tool_use",
                    id="c1",
                    name="make_chart",
                    input={
                        "query_id": "q1",
                        "kind": "bar",
                        "x": "competitor",
                        "y": "salary",
                        "series": None,
                        "title": "x",
                    },
                ),
                block(
                    "tool_use",
                    id="c2",
                    name="make_chart",
                    input={
                        "query_id": "q1",
                        "kind": "bar",
                        "x": "competitor",
                        "y": "open_postings",
                        "series": None,
                        "title": "Offene Stellen",
                    },
                ),
            ),  # fmt: skip
            reply("end_turn", block("text", text="dm hat 3 offene Stellen und das ist der Stand.")),
        ]
    )
    session = Session(client, mart, log_file=None)
    answer = session.ask("Grafik bitte", "de")
    results = session.messages[4]["content"]
    assert results[0]["is_error"] and "salary" in results[0]["content"]
    assert answer.charts == [
        {"query_id": "q1", "kind": "bar", "x": "competitor", "y": "open_postings", "series": None,
         "title": "Offene Stellen", "chart_id": "c1", "columns": ["competitor", "open_postings"],
         "rows": [["dm", 3]]}
    ]  # fmt: skip


def test_history_is_append_only(mart):
    client = ScriptedClient(
        [
            reply("tool_use", sql_call(QUERY)),
            reply("end_turn", block("text", text="dm hat 3 offene Stellen und das ist der Stand.")),
            reply("end_turn", block("text", text="Ja, es sind 3 und das bleibt so.")),
        ]
    )
    session = Session(client, mart, log_file=None)
    session.ask("Wie viele Stellen hat dm?", "de")
    before = list(session.messages)
    session.ask("Sicher?", "de")
    assert session.messages[: len(before)] == before
