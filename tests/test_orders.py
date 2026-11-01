import logging
from datetime import datetime

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from database import get_db
from main import app


def stock_by_product_id(client):
    response = client.get("/products/", params={"limit": 100})
    return {product["id"]: product["stock"] for product in response.json()}


def test_pedido_exitoso_aplica_descuento_calcula_total_y_descuenta_stock(
    client, user, create_product
):
    con_descuento = create_product(name="Monitor", price=100.05, stock=5)
    sin_descuento = create_product(name="Teclado", price=100.00, stock=10)

    response = client.post(
        "/orders/",
        json={
            "user_id": user["id"],
            "items": [
                {"product_id": con_descuento["id"], "quantity": 2},
                {"product_id": sin_descuento["id"], "quantity": 3},
            ],
        },
    )

    assert response.status_code == 201
    order = response.json()
    assert order["user_id"] == user["id"]
    # 2 x 90.05 (100.05 con 10 % de descuento) + 3 x 100.00 (sin descuento)
    assert order["total_price"] == 480.10
    assert datetime.fromisoformat(order["created_at"]).tzinfo is not None
    items = sorted(order["items"], key=lambda item: item["product_id"])
    assert items == [
        {
            "product_id": con_descuento["id"],
            "product_name": "Monitor",
            "quantity": 2,
            "unit_price": 90.05,
        },
        {
            "product_id": sin_descuento["id"],
            "product_name": "Teclado",
            "quantity": 3,
            "unit_price": 100.00,
        },
    ]
    assert stock_by_product_id(client) == {
        con_descuento["id"]: 3,
        sin_descuento["id"]: 7,
    }


def test_pedido_con_product_id_repetido_suma_cantidades_en_una_linea(
    client, user, create_product
):
    mouse = create_product(name="Mouse", price=20, stock=10)

    response = client.post(
        "/orders/",
        json={
            "user_id": user["id"],
            "items": [
                {"product_id": mouse["id"], "quantity": 2},
                {"product_id": mouse["id"], "quantity": 3},
            ],
        },
    )

    assert response.status_code == 201
    order = response.json()
    assert order["items"] == [
        {
            "product_id": mouse["id"],
            "product_name": "Mouse",
            "quantity": 5,
            "unit_price": 20.00,
        }
    ]
    assert order["total_price"] == 100.00
    assert stock_by_product_id(client) == {mouse["id"]: 5}


def test_pedido_con_stock_insuficiente_devuelve_409_sin_efectos_parciales(
    client, user, create_product
):
    con_stock = create_product(name="Mouse", price=20, stock=10)
    sin_stock = create_product(name="Monitor", price=300, stock=1)

    response = client.post(
        "/orders/",
        json={
            "user_id": user["id"],
            "items": [
                {"product_id": con_stock["id"], "quantity": 2},
                {"product_id": sin_stock["id"], "quantity": 2},
            ],
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            f"Stock insuficiente para el producto 'Monitor' "
            f"(id {sin_stock['id']}): disponible 1, solicitado 2"
        )
    }
    assert stock_by_product_id(client) == {
        con_stock["id"]: 10,
        sin_stock["id"]: 1,
    }
    assert client.get(f"/users/{user['id']}/orders").json() == []


def test_pedido_con_lineas_repetidas_que_superan_el_stock_devuelve_409(
    client, user, create_product
):
    mouse = create_product(name="Mouse", price=20, stock=5)

    # Cada línea cabe en el stock por separado, pero la suma (6) no.
    response = client.post(
        "/orders/",
        json={
            "user_id": user["id"],
            "items": [
                {"product_id": mouse["id"], "quantity": 3},
                {"product_id": mouse["id"], "quantity": 3},
            ],
        },
    )

    assert response.status_code == 409
    assert stock_by_product_id(client) == {mouse["id"]: 5}


def test_pedido_de_usuario_inexistente_devuelve_404(client, create_product):
    mouse = create_product(name="Mouse", stock=10)

    response = client.post(
        "/orders/",
        json={
            "user_id": 999,
            "items": [{"product_id": mouse["id"], "quantity": 1}],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Usuario no encontrado"}
    assert stock_by_product_id(client) == {mouse["id"]: 10}


def test_pedido_con_producto_inexistente_devuelve_404_con_sus_ids(
    client, user, create_product
):
    mouse = create_product(name="Mouse", stock=10)

    response = client.post(
        "/orders/",
        json={
            "user_id": user["id"],
            "items": [
                {"product_id": mouse["id"], "quantity": 1},
                {"product_id": 999, "quantity": 1},
            ],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Productos no encontrados: 999"}
    assert stock_by_product_id(client) == {mouse["id"]: 10}
    assert client.get(f"/users/{user['id']}/orders").json() == []


@pytest.mark.parametrize(
    "items",
    [[], [{"product_id": 1, "quantity": 0}]],
    ids=["items_vacio", "quantity_0"],
)
def test_pedido_con_items_invalidos_devuelve_422(client, user, items):
    response = client.post(
        "/orders/",
        json={"user_id": user["id"], "items": items},
    )

    assert response.status_code == 422


def test_historial_muestra_pedidos_del_mas_reciente_al_mas_antiguo(
    client, user, create_product
):
    teclado = create_product(name="Teclado", price=50, stock=10)
    monitor = create_product(name="Monitor", price=250, stock=10)
    primero = client.post(
        "/orders/",
        json={
            "user_id": user["id"],
            "items": [{"product_id": teclado["id"], "quantity": 1}],
        },
    ).json()
    segundo = client.post(
        "/orders/",
        json={
            "user_id": user["id"],
            "items": [{"product_id": monitor["id"], "quantity": 2}],
        },
    ).json()

    response = client.get(f"/users/{user['id']}/orders")

    assert response.status_code == 200
    orders = response.json()
    assert [order["id"] for order in orders] == [segundo["id"], primero["id"]]
    assert [order["items"][0]["product_name"] for order in orders] == [
        "Monitor",
        "Teclado",
    ]
    assert orders == [segundo, primero]


def test_historial_no_incluye_pedidos_de_otros_usuarios(
    client, create_user, create_product
):
    ana = create_user(name="Ana", email="ana@example.com")
    luis = create_user(name="Luis", email="luis@example.com")
    mouse = create_product(name="Mouse", stock=10)
    client.post(
        "/orders/",
        json={
            "user_id": luis["id"],
            "items": [{"product_id": mouse["id"], "quantity": 1}],
        },
    )

    response = client.get(f"/users/{ana['id']}/orders")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    ("user_id", "product_id"),
    [(2**63, 1), (1, 2**63)],
    ids=["user_id", "product_id"],
)
def test_pedido_con_id_fuera_de_rango_no_devuelve_500(
    client, user, user_id, product_id
):
    response = client.post(
        "/orders/",
        json={
            "user_id": user_id,
            "items": [{"product_id": product_id, "quantity": 1}],
        },
    )

    # Antes de la corrección: OverflowError en SQLite → 500 en texto plano.
    assert response.status_code == 422


def test_pedido_cuyo_total_excede_la_columna_total_price_responde_422(
    client, user, create_product
):
    portatil = create_product(name="Portátil", price=3_000_000, stock=50)

    # 40 x 2.700.000 (con descuento) = 108.000.000 > 99.999.999,99
    response = client.post(
        "/orders/",
        json={
            "user_id": user["id"],
            "items": [{"product_id": portatil["id"], "quantity": 40}],
        },
    )

    # Antes de la corrección: 201 en SQLite y 500 en MySQL ("Out of range").
    assert response.status_code == 422
    assert "supera el máximo permitido" in response.json()["detail"]
    productos = client.get("/products/").json()
    assert productos[0]["stock"] == 50


class SessionWithoutDatabase:
    """Sesión falsa: la primera consulta falla como si la BD se hubiera caído."""

    def get(self, *args, **kwargs):
        raise OperationalError(
            "SELECT ...", None, Exception("Lost connection to MySQL server")
        )


def test_error_de_base_de_datos_devuelve_500_sin_exponer_detalles(
    client, caplog
):
    app.dependency_overrides[get_db] = SessionWithoutDatabase

    with caplog.at_level(logging.ERROR, logger="main"):
        response = client.post(
            "/orders/",
            json={"user_id": 1, "items": [{"product_id": 1, "quantity": 1}]},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Error interno de base de datos"}
    assert "Error de base de datos en POST /orders/" in caplog.text


def test_consulta_de_productos_del_pedido_bloquea_filas_en_mysql(
    client, user, create_product
):
    # SQLite ignora FOR UPDATE, así que se captura la consulta real que
    # ejecuta el endpoint y se compila con el dialecto de MySQL.
    mouse = create_product(name="Mouse", stock=10)
    statements = []

    def capture_statement(orm_execute_state):
        statements.append(orm_execute_state.statement)

    event.listen(Session, "do_orm_execute", capture_statement)
    try:
        response = client.post(
            "/orders/",
            json={
                "user_id": user["id"],
                "items": [{"product_id": mouse["id"], "quantity": 1}],
            },
        )
    finally:
        event.remove(Session, "do_orm_execute", capture_statement)

    assert response.status_code == 201
    mysql_sql = [str(stmt.compile(dialect=mysql.dialect())) for stmt in statements]
    locking_queries = [sql for sql in mysql_sql if "FOR UPDATE" in sql]
    assert len(locking_queries) == 1
    assert "FROM products" in locking_queries[0]
    assert "products.id IN" in locking_queries[0]
