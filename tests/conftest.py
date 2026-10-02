import os
import tempfile

# La app guarda datos en una carpeta temporal durante los tests.
os.environ["FACELESS_DATA_DIR"] = tempfile.mkdtemp(prefix="faceless-test-")
# Los tests ejecutan las tareas a mano, sin trabajador en segundo plano.
os.environ["FACELESS_WORKER"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:  # el arranque crea las tablas
        yield c


def register(client, username="ana", password="contrasena123"):
    return client.post(
        "/registro",
        data={"username": username, "password": password, "password_confirm": password},
    )


@pytest.fixture
def logged_in(client):
    register(client)
    return client
