import pytest


def test_crear_usuario_devuelve_201_con_sus_datos(client):
    response = client.post(
        "/users/",
        json={"name": "Ana Pérez", "email": "ana.perez@example.com"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "name": "Ana Pérez",
        "email": "ana.perez@example.com",
    }


def test_crear_usuario_con_nombre_de_50_caracteres_es_valido(client):
    response = client.post(
        "/users/",
        json={"name": "a" * 50, "email": "ana.perez@example.com"},
    )

    assert response.status_code == 201


def test_crear_usuario_con_email_duplicado_devuelve_409(client, user):
    response = client.post(
        "/users/",
        json={"name": "Otra Ana", "email": user["email"]},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Ya existe un usuario con ese email"}


def test_email_se_guarda_en_minusculas_y_el_duplicado_no_depende_de_ellas(
    client,
):
    response = client.post(
        "/users/",
        json={"name": "Ana", "email": "ANA@Example.com"},
    )
    duplicate = client.post(
        "/users/",
        json={"name": "Ana", "email": "ana@example.com"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "ana@example.com"
    assert duplicate.status_code == 409


@pytest.mark.parametrize(
    "email",
    ["no-es-un-email", "ana@", "a" * 50 + "@" + "b" * 46 + ".com"],
    ids=["sin_arroba", "sin_dominio", "mas_de_100_caracteres"],
)
def test_crear_usuario_con_email_invalido_devuelve_422(client, email):
    response = client.post("/users/", json={"name": "Ana", "email": email})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "name",
    ["", "   ", "a" * 51],
    ids=["vacio", "solo_espacios", "mas_de_50_caracteres"],
)
def test_crear_usuario_con_nombre_invalido_devuelve_422(client, name):
    response = client.post(
        "/users/",
        json={"name": name, "email": "ana.perez@example.com"},
    )

    assert response.status_code == 422


def test_historial_de_usuario_inexistente_devuelve_404(client):
    response = client.get("/users/999/orders")

    assert response.status_code == 404
    assert response.json() == {"detail": "Usuario no encontrado"}


def test_historial_de_usuario_sin_pedidos_devuelve_lista_vacia(client, user):
    response = client.get(f"/users/{user['id']}/orders")

    assert response.status_code == 200
    assert response.json() == []


def test_historial_con_user_id_fuera_de_rango_no_devuelve_500(client):
    response = client.get(f"/users/{2**63}/orders")

    # Antes de la corrección: OverflowError en SQLite → 500 en texto plano.
    assert response.status_code == 422
