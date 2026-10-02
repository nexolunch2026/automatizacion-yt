from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA foreign_keys=ON")
    # WAL permite que la web y el trabajador en segundo plano escriban a la vez.
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA busy_timeout=5000")


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from app import models  # noqa: F401 — registra las tablas

    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Añade a las tablas existentes las columnas nuevas (siempre opcionales), para que
    al actualizar el programa no se pierdan los datos del usuario."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing and column.nullable:
                    kind = column.type.compile(dialect=engine.dialect)
                    conn.execute(
                        text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}')
                    )


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
