import os

# database.py exige DATABASE_URL al importarse: hay que definirla antes de
# importar la app. Se fuerza SQLite en memoria para que las pruebas nunca
# toquen una base real aunque el desarrollador tenga DATABASE_URL exportada.
os.environ["DATABASE_URL"] = "sqlite://"

from contextlib import contextmanager  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from database import Base  # noqa: E402
from database import get_db  # noqa: E402
from main import app  # noqa: E402


# SQLite en memoria compartido por todas las conexiones (StaticPool) y usable
# desde el hilo en el que TestClient ejecuta la app.
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_db():
    """Base de datos limpia por prueba y app apuntando a ella."""
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(test_db):
    """Sesión directa a la base de pruebas, para preparar datos."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def count_queries():
    """Devuelve un context manager que registra las sentencias SQL."""

    @contextmanager
    def _count_queries():
        statements = []

        def record(conn, cursor, statement, parameters, context, many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            yield statements
        finally:
            event.remove(engine, "before_cursor_execute", record)

    return _count_queries


@pytest.fixture
def client(test_db):
    # El bloque with ejecuta el lifespan de la app.
    with TestClient(app) as c:
        yield c


@pytest.fixture
def create_user(client):
    def _create_user(name="Ana Pérez", email="ana.perez@example.com"):
        response = client.post("/users/", json={"name": name, "email": email})
        assert response.status_code == 201, response.text
        return response.json()

    return _create_user


@pytest.fixture
def user(create_user):
    return create_user()


@pytest.fixture
def create_product(client):
    def _create_product(name="Producto", price=10, stock=10):
        response = client.post(
            "/products/",
            json={"name": name, "price": price, "stock": stock},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _create_product
