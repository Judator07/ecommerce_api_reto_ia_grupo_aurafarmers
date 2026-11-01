import pytest


def test_crear_producto_devuelve_201_con_precio_como_numero_json(client):
    response = client.post(
        "/products/",
        json={"name": "Teclado mecánico", "price": 199.99, "stock": 25},
    )

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": 1,
        "name": "Teclado mecánico",
        "price": 199.99,
        "stock": 25,
    }
    # Un Decimal serializado como texto llegaría como str ("199.99").
    assert isinstance(body["price"], float)


@pytest.mark.parametrize(
    "price",
    [0, -10, 10.999],
    ids=["cero", "negativo", "mas_de_2_decimales"],
)
def test_crear_producto_con_precio_invalido_devuelve_422(client, price):
    response = client.post(
        "/products/",
        json={"name": "Teclado", "price": price, "stock": 5},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "stock",
    [-1, 2**31],
    ids=["negativo", "mayor_a_int"],
)
def test_crear_producto_con_stock_fuera_de_rango_devuelve_422(client, stock):
    response = client.post(
        "/products/",
        json={"name": "Teclado", "price": 50, "stock": stock},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        '{"name": "Teclado", "price": NaN, "stock": 5}',
        '{"name": "Teclado", "price": 50, "stock": Infinity}',
    ],
    ids=["price_nan", "stock_infinity"],
)
def test_crear_producto_con_nan_o_infinity_devuelve_422(client, body):
    # Antes: el manejador por defecto repetía el NaN en la respuesta, no lo
    # podía serializar y la API respondía 500.
    response = client.post(
        "/products/",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_crear_producto_con_nombre_de_solo_espacios_devuelve_422(client):
    response = client.post(
        "/products/",
        json={"name": "   ", "price": 50, "stock": 5},
    )

    assert response.status_code == 422


def test_listar_productos_ordena_por_id_en_la_consulta(client, count_queries):
    # SQLite devuelve el orden de inserción aunque falte ORDER BY; por eso se
    # revisa la consulta enviada a la base de datos.
    with count_queries() as statements:
        client.get("/products/")

    assert any("ORDER BY products.id" in sql for sql in statements)


def test_listar_productos_por_defecto_devuelve_10_ordenados_por_id(
    client, create_product
):
    ids = [create_product(name=f"Producto {n}")["id"] for n in range(12)]

    response = client.get("/products/")

    assert response.status_code == 200
    assert [product["id"] for product in response.json()] == ids[:10]


def test_listar_productos_respeta_limit_y_offset(client, create_product):
    ids = [create_product(name=f"Producto {n}")["id"] for n in range(5)]

    response = client.get("/products/", params={"limit": 2, "offset": 1})

    assert response.status_code == 200
    assert [product["id"] for product in response.json()] == ids[1:3]


def test_listar_productos_con_offset_mas_alla_del_final_devuelve_lista_vacia(
    client, create_product
):
    create_product(name="Producto 1")
    create_product(name="Producto 2")

    response = client.get("/products/", params={"offset": 2})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}],
    ids=["limit_0", "limit_101", "offset_negativo"],
)
def test_listar_productos_con_paginacion_fuera_de_rango_devuelve_422(
    client, params
):
    response = client.get("/products/", params=params)

    assert response.status_code == 422
