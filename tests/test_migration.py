from sqlalchemy import inspect, text

from app.db import engine, init_db


def test_old_database_gets_new_columns_without_losing_data(client):
    # Simula una base de datos de la versión anterior (sin la columna jobs.params).
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE jobs DROP COLUMN params"))
        conn.execute(text("INSERT INTO users (username, password_hash) VALUES ('ana', 'x')"))
    assert "params" not in {c["name"] for c in inspect(engine).get_columns("jobs")}

    init_db()

    assert "params" in {c["name"] for c in inspect(engine).get_columns("jobs")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT username FROM users")).scalar() == "ana"
