"""Hardening test for a real production symptom: a user-supplied card name that doesn't
exactly match the seeded corpus (a typo, wrong case, or stray whitespace) used to produce the
same opaque "No retrieved evidence" refusal as a genuinely uncovered category, with no way to
tell the two apart. agents/nodes/retrieve.py now flags this distinctly via
`unrecognized_cards`, surfaced by agents/nodes/validate.py as a specific, actionable message.
"""

from agents.nodes.retrieve import retrieve
from database.db import SessionLocal


def _config(db):
    return {"configurable": {"db": db}}


def test_a_mistyped_card_name_is_flagged_as_unrecognized():
    db = SessionLocal()
    try:
        result = retrieve(
            {"user_query": "Spending Rs. 50,000 on flights", "cards_owned": ["axis atlas"]},
            _config(db),
        )
    finally:
        db.close()

    assert result["retrieved_chunks"] == []
    assert result["unrecognized_cards"] == ["axis atlas"]


def test_a_correctly_spelled_card_name_is_not_flagged():
    db = SessionLocal()
    try:
        result = retrieve(
            {"user_query": "Spending Rs. 50,000 on flights", "cards_owned": ["Axis Atlas"]},
            _config(db),
        )
    finally:
        db.close()

    assert result["retrieved_chunks"] != []
    assert "unrecognized_cards" not in result


def test_a_correctly_spelled_card_with_no_matching_evidence_is_not_flagged():
    """A card that's spelled right but genuinely has no chunks similar enough to this query
    (as opposed to a name that doesn't exist at all) must still get the generic message, not
    the "check your spelling" one - it would be actively misleading here.
    """
    db = SessionLocal()
    try:
        result = retrieve(
            {
                "user_query": "asdkjfh qwoeiruqwoeiru nonsense query zzz",
                "cards_owned": ["Axis Atlas"],
            },
            _config(db),
        )
    finally:
        db.close()

    if not result["retrieved_chunks"]:
        assert result["unrecognized_cards"] == []
