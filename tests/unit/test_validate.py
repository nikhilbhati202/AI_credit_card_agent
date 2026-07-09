from agents.nodes.validate import validate_rules


def test_passes_when_chunks_were_retrieved():
    result = validate_rules({"retrieved_chunks": [{"chunk_id": 1}]})
    assert result["evidence_sufficient"] is True


def test_generic_refusal_when_no_chunks_and_cards_were_recognized():
    result = validate_rules({"retrieved_chunks": [], "unrecognized_cards": []})
    assert result["evidence_sufficient"] is False
    assert result["evidence_reason"] == (
        "No retrieved evidence above the similarity threshold for the cards you own."
    )


def test_specific_refusal_when_cards_owned_does_not_match_any_known_card():
    result = validate_rules({"retrieved_chunks": [], "unrecognized_cards": ["axis atlas"]})
    assert result["evidence_sufficient"] is False
    assert "axis atlas" in result["evidence_reason"]
    assert "case- and whitespace-sensitive" in result["evidence_reason"]
