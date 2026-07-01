from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_profile_lifecycle_create_then_read():
    user_id = "test-user-phase2"

    put_response = client.put(
        "/api/v1/user/profile",
        json={
            "user_id": user_id,
            "cards_owned": ["Axis Atlas", "Axis ACE"],
            "preferences": {"prefers": "miles"},
        },
    )
    assert put_response.status_code == 200
    body = put_response.json()
    assert body["cards_owned"] == ["Axis Atlas", "Axis ACE"]
    assert body["preferences"] == {"prefers": "miles"}

    get_response = client.get(f"/api/v1/user/profile?user_id={user_id}")
    assert get_response.status_code == 200
    assert get_response.json()["cards_owned"] == ["Axis Atlas", "Axis ACE"]


def test_profile_not_found_returns_404():
    response = client.get("/api/v1/user/profile?user_id=does-not-exist-xyz")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_list_cards_includes_seeded_real_cards():
    response = client.get("/api/v1/cards")
    assert response.status_code == 200
    card_names = {c["card_name"] for c in response.json()}
    assert "Axis Atlas" in card_names
    assert "SBI Cashback" in card_names
