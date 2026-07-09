"""Headless tests for the Streamlit UI (guide Section 17) using streamlit.testing.v1.AppTest -
this drives the real script (widget interactions, session_state, conditional rendering)
without a browser, the same "test the actual behavior, not just import the module" standard
the rest of the suite holds itself to.

requests.post is mocked (patching app.streamlit_app.requests.post) so these tests never need a
live API or LLM - the UI's own logic (which endpoint to call, how to render each response
shape, whether the approval gate blocks chat_input) is what's under test here.
"""

from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

APP_PATH = "app/streamlit_app.py"


def _response(json_body: dict, status_code: int = 200) -> MagicMock:
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_body
    return mock_response


def test_renders_without_error_on_first_load() -> None:
    at = AppTest.from_file(APP_PATH).run()
    assert not at.exception


def test_recommendation_response_renders_as_a_structured_card() -> None:
    at = AppTest.from_file(APP_PATH).run()
    with patch("app.streamlit_app.requests.post") as mock_post:
        mock_post.return_value = _response(
            {
                "session_id": "session-1",
                "recommended_card": "Axis Atlas",
                "estimated_reward_value": 2500.0,
                "effective_return_pct": 5.0,
                "calculation": {
                    "spend_amount": 50000.0,
                    "reward_rate": 5.0,
                    "reward_unit": "miles",
                    "point_valuation": 1.0,
                    "cap_applied": False,
                },
                "rules_used": [{"card_name": "Axis Atlas", "excerpt": "5 EDGE Miles per Rs.100"}],
                "caps_or_exclusions": [],
                "assumptions": ["Monthly cap assumed unused."],
                "alternatives": [],
                "confidence": "High",
                "insufficient_information": False,
                "message": None,
                "explanation": "Axis Atlas earns the most for this flight spend.",
                "approval_pending": False,
                "transfer_proposal": None,
            }
        )
        at.chat_input[0].set_value("Spending Rs. 50,000 on flights").run()

    assert not at.exception
    mock_post.assert_called_once()
    called_path = mock_post.call_args[0][0]
    assert called_path.endswith("/recommend")
    assert any("Axis Atlas" in success.value for success in at.success)
    assert at.session_state["session_id"] == "session-1"


def test_a_capped_reward_shows_the_before_and_after_breakdown() -> None:
    at = AppTest.from_file(APP_PATH).run()
    with patch("app.streamlit_app.requests.post") as mock_post:
        mock_post.return_value = _response(
            {
                "session_id": "session-cap",
                "recommended_card": "Axis ACE",
                "estimated_reward_value": 500.0,
                "effective_return_pct": 1.25,
                "spend_category": "utility_bills",
                "calculation": {
                    "spend_amount": 40000.0,
                    "reward_rate": 5.0,
                    "reward_unit": "cashback",
                    "point_valuation": 1.0,
                    "cap_applied": True,
                    "reward_units_earned": 500.0,
                    "uncapped_reward_value": 2000.0,
                },
                "rules_used": [],
                "caps_or_exclusions": ["Rs.500/statement cap"],
                "assumptions": [],
                "alternatives": [],
                "confidence": "High",
                "insufficient_information": False,
                "message": None,
                "explanation": "Capped at Rs. 500.",
                "approval_pending": False,
                "transfer_proposal": None,
            }
        )
        at.chat_input[0].set_value("40000 on utility bills").run()

    assert not at.exception
    all_text = " ".join(m.value for m in at.markdown)
    assert "2,000.00" in all_text  # the uncapped/potential value is shown
    all_captions = " ".join(c.value for c in at.caption)
    assert "cashback" in all_captions.lower()  # point-valuation-not-applicable note


def test_insufficient_information_renders_as_a_warning() -> None:
    at = AppTest.from_file(APP_PATH).run()
    with patch("app.streamlit_app.requests.post") as mock_post:
        mock_post.return_value = _response(
            {
                "session_id": "session-2",
                "recommended_card": None,
                "insufficient_information": True,
                "message": "I don't have an active rule for 'insurance' spend.",
                "approval_pending": False,
                "transfer_proposal": None,
            }
        )
        at.chat_input[0].set_value("Spending 5000 on insurance").run()

    assert not at.exception
    assert any("insurance" in warning.value for warning in at.warning)


def test_follow_up_question_is_shown_and_input_stays_open() -> None:
    at = AppTest.from_file(APP_PATH).run()
    with patch("app.streamlit_app.requests.post") as mock_post:
        mock_post.return_value = _response(
            {
                "session_id": "session-3",
                "follow_up_question": "How much are you planning to spend, and on what?",
                "approval_pending": False,
                "transfer_proposal": None,
            }
        )
        at.chat_input[0].set_value("Which card should I use?").run()

    assert not at.exception
    assert any("How much are you planning to spend" in markdown.value for markdown in at.markdown)
    # The clarification loop continues on the same endpoint - chat input must still be open.
    assert len(at.chat_input) == 1


class TestTransferApprovalGate:
    def test_pending_approval_blocks_further_chat_input(self) -> None:
        at = AppTest.from_file(APP_PATH).run()
        with patch("app.streamlit_app.requests.post") as mock_post:
            mock_post.return_value = _response(
                {
                    "session_id": "session-4",
                    "approval_pending": True,
                    "transfer_proposal": {
                        "card_name": "Axis Atlas",
                        "partner_name": "Singapore Airlines KrisFlyer",
                        "miles_amount": 10000,
                        "transfer_ratio": "1.0:2.0",
                        "transfer_value": 500.0,
                        "direct_redemption_value": 10000.0,
                        "better_option": "redeem_directly",
                        "confidence_score": 0.75,
                        "source_note": "Cross-checked across secondary sources.",
                    },
                }
            )
            at.chat_input[0].set_value("Transfer 10000 miles to KrisFlyer").run()
            # The app's own st.rerun() (needed so the approval gate replaces the chat input on
            # the very next paint) only takes effect on the following script pass - mirroring
            # a real browser round-trip, drive that pass explicitly.
            at.run()

        assert not at.exception
        assert at.session_state["pending_proposal"] is not None
        # The approval gate is showing, so the chat input must be gone from this render.
        assert len(at.chat_input) == 0
        confirm_buttons = [b for b in at.button if b.label == "Confirm transfer"]
        cancel_buttons = [b for b in at.button if b.label == "Cancel transfer"]
        assert len(confirm_buttons) == 1
        assert len(cancel_buttons) == 1

    def test_confirming_resolves_the_gate_and_reopens_chat_input(self) -> None:
        at = AppTest.from_file(APP_PATH).run()
        with patch("app.streamlit_app.requests.post") as mock_post:
            mock_post.return_value = _response(
                {
                    "session_id": "session-5",
                    "approval_pending": True,
                    "transfer_proposal": {
                        "card_name": "Axis Atlas",
                        "partner_name": "Singapore Airlines KrisFlyer",
                        "miles_amount": 10000,
                        "transfer_ratio": "1.0:2.0",
                        "transfer_value": 500.0,
                        "direct_redemption_value": 10000.0,
                        "better_option": "redeem_directly",
                        "confidence_score": 0.75,
                        "source_note": None,
                    },
                }
            )
            at.chat_input[0].set_value("Transfer 10000 miles to KrisFlyer").run()

            mock_post.return_value = _response(
                {
                    "session_id": "session-5",
                    "approval_status": "approved",
                    "transfer_proposal": {
                        "card_name": "Axis Atlas",
                        "partner_name": "Singapore Airlines KrisFlyer",
                    },
                    "message": "Transfer confirmed: 10000 miles from Axis Atlas to Singapore "
                    "Airlines KrisFlyer.",
                }
            )
            confirm_button = next(b for b in at.button if b.label == "Confirm transfer")
            confirm_button.click().run()

        assert not at.exception
        assert mock_post.call_args[0][0].endswith("/transfer/confirm")
        assert mock_post.call_args.kwargs["json"]["approved"] is True
        assert at.session_state["pending_proposal"] is None
        # The gate is resolved - a fresh chat input must be available again.
        assert len(at.chat_input) == 1

    def test_cancelling_sends_approved_false(self) -> None:
        at = AppTest.from_file(APP_PATH).run()
        with patch("app.streamlit_app.requests.post") as mock_post:
            mock_post.return_value = _response(
                {
                    "session_id": "session-6",
                    "approval_pending": True,
                    "transfer_proposal": {
                        "card_name": "Axis Atlas",
                        "partner_name": "Singapore Airlines KrisFlyer",
                        "miles_amount": 10000,
                        "transfer_ratio": "1.0:2.0",
                        "transfer_value": 500.0,
                        "direct_redemption_value": 10000.0,
                        "better_option": "redeem_directly",
                        "confidence_score": 0.75,
                        "source_note": None,
                    },
                }
            )
            at.chat_input[0].set_value("Transfer 10000 miles to KrisFlyer").run()

            mock_post.return_value = _response(
                {
                    "session_id": "session-6",
                    "approval_status": "rejected",
                    "transfer_proposal": None,
                    "message": "Transfer cancelled at your request - no action was taken.",
                }
            )
            cancel_button = next(b for b in at.button if b.label == "Cancel transfer")
            cancel_button.click().run()

        assert not at.exception
        assert mock_post.call_args.kwargs["json"]["approved"] is False
        assert at.session_state["pending_proposal"] is None


def test_api_error_is_shown_without_crashing_the_app() -> None:
    at = AppTest.from_file(APP_PATH).run()
    with patch("app.streamlit_app.requests.post") as mock_post:
        mock_post.return_value = _response(
            {"error": {"code": "llm_not_configured", "message": "ANTHROPIC_API_KEY is not set."}},
            status_code=503,
        )
        at.chat_input[0].set_value("Spending 5000 on groceries").run()

    assert not at.exception
    assert any("ANTHROPIC_API_KEY" in error.value for error in at.error)


def test_reset_conversation_clears_session_state() -> None:
    at = AppTest.from_file(APP_PATH).run()
    with patch("app.streamlit_app.requests.post") as mock_post:
        mock_post.return_value = _response(
            {
                "session_id": "session-7",
                "recommended_card": "Axis Atlas",
                "insufficient_information": False,
                "approval_pending": False,
                "transfer_proposal": None,
            }
        )
        at.chat_input[0].set_value("Spending 50000 on flights").run()

    assert at.session_state["session_id"] == "session-7"
    at.sidebar.button[0].click().run()
    assert at.session_state["session_id"] is None
    assert at.session_state["messages"] == []
