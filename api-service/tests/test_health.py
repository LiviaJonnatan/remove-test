"""Startup and the health check the frontend and compose rely on."""

import pytest
from fastapi.testclient import TestClient

from conftest import DEV_DOCKET, make_chunk
from main import PassageIndex, create_app

TRANSFER_DOCKET = "EPA-HQ-OAR-2017-0355"


def test_health_reports_the_passages_the_api_can_search(store):
    store.upsert([
        make_chunk(0, "Tributaries with ephemeral flow."),
        make_chunk(1, "Ditches are excluded."),
        make_chunk(0, "Repeal of the Clean Power Plan.", docket=TRANSFER_DOCKET, doc="2017-22349"),
    ])  # fmt: skip
    app = create_app(lambda: PassageIndex(store))
    # Used as a context manager, TestClient runs the app's startup, like uvicorn does.
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "passages": 3,
        "dockets": [TRANSFER_DOCKET, DEV_DOCKET],
        "linker": None,
    }


def test_the_api_refuses_to_start_on_an_empty_index(store):
    app = create_app(lambda: PassageIndex(store))
    with pytest.raises(RuntimeError, match="is empty"), TestClient(app):
        pass
