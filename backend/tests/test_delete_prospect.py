"""
Deleting one prospect (the minus button on the Prospects page): removed from
lists and campaigns, but kept when they've been emailed or opted out.
"""
from contextlib import asynccontextmanager

import pytest


@pytest.fixture(scope="module")
def client():
    import app.main as main
    from app.database import init_db
    from fastapi.testclient import TestClient

    init_db()

    @asynccontextmanager
    async def no_lifespan(app):  # never start the schedulers
        yield

    main.app.router.lifespan_context = no_lifespan
    client = TestClient(main.app)
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/signup", json={"email": "deleter@workspace.test", "password": "Test-pass-12345", "name": "Owner"}
    )
    assert response.status_code == 200, response.text
    return client


def _add(client, email):
    response = client.post("/api/v1/leads/people", json={"email": email})
    assert response.status_code == 200, response.text
    return response.json()


def _person_id(client, email):
    people = client.get("/api/v1/leads/people", params={"search": email}).json()["people"]
    return people[0]["id"] if people else None


def test_deletes_a_new_prospect(client):
    _add(client, "gone@prospect.test")
    person_id = _person_id(client, "gone@prospect.test")

    response = client.delete(f"/api/v1/leads/people/{person_id}")

    assert response.status_code == 200, response.text
    assert response.json()["deleted"] == 1
    assert _person_id(client, "gone@prospect.test") is None
    assert client.delete(f"/api/v1/leads/people/{person_id}").status_code == 404


def test_keeps_an_opted_out_prospect(client):
    _add(client, "optout@prospect.test")
    person_id = _person_id(client, "optout@prospect.test")
    client.patch(f"/api/v1/leads/people/{person_id}/status", params={"status": "unsubscribed"})

    response = client.delete(f"/api/v1/leads/people/{person_id}")

    assert response.status_code == 409
    assert "unsubscribed" in response.json()["detail"]
    assert _person_id(client, "optout@prospect.test") == person_id
