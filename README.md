# API de E-commerce — Reto IA en Ingeniería de Software UIS

API REST en **FastAPI** para gestionar usuarios, productos y pedidos de una tienda en línea.
Este repositorio es un fork de [`chaphe/ecommerce_api_reto_ia`](https://github.com/chaphe/ecommerce_api_reto_ia):
el código original fue auditado, corregido, probado, documentado y dockerizado con la ayuda de la
herramienta de IA **Claude Code**, como parte del reto práctico del curso 22969 – Ingeniería de Software I
(Universidad Industrial de Santander).

- Auditoría, correcciones y registro de sugerencias de la IA: [`AUDITORIA.md`](AUDITORIA.md)
- Documentación interactiva (con la API en ejecución): <http://localhost:8000/docs> (Swagger) y <http://localhost:8000/redoc>

## Contenido

1. [Arquitectura](#arquitectura)
2. [Reglas de negocio](#reglas-de-negocio)
3. [Endpoints](#endpoints)
4. [Ejecución con Docker (recomendada)](#ejecución-con-docker-recomendada)
5. [Ejecución local sin Docker](#ejecución-local-sin-docker)
6. [Pruebas](#pruebas)
7. [Ejemplos de uso](#ejemplos-de-uso)
8. [Notas](#notas)
9. [Autores](#autores)

## Arquitectura

**Tecnologías:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, PyMySQL, MySQL 8.4, Uvicorn,
pytest y Docker Compose.

La aplicación conserva la estructura plana del proyecto original, con cuatro módulos y una
responsabilidad clara por módulo:

```text
.
├── main.py              # Aplicación FastAPI: endpoints, reglas de negocio y manejo de errores
├── schemas.py           # Schemas Pydantic: validación de entradas y forma de las respuestas
├── models.py            # Modelos ORM de SQLAlchemy (tablas y relaciones)
├── database.py          # Conexión (DATABASE_URL), engine, sesión y dependencia get_db
├── tests/               # Pruebas unitarias y de integración (pytest)
├── Dockerfile           # Imagen de la API
├── docker-compose.yml   # API + MySQL con volumen persistente
├── .env.example         # Plantilla de variables de entorno (copiar a .env)
├── requirements.txt     # Dependencias de ejecución
└── requirements-dev.txt # Dependencias de desarrollo y pruebas
```

| Capa | Módulo | Responsabilidad |
|---|---|---|
| Presentación (HTTP) | `main.py` | Rutas, códigos de estado, documentación OpenAPI y manejador global de errores de BD. |
| Lógica de negocio | `main.py` | Descuento (`apply_discount`), validación de stock y creación atómica de pedidos. |
| Contratos de datos | `schemas.py` | Validación de lo que entra (`*Create`) y serialización de lo que sale (`*Out`). |
| Persistencia | `models.py`, `database.py` | Tablas, restricciones y relaciones; sesión por petición con `get_db`. |

**Flujo de una petición** (ejemplo `POST /orders/`):

1. `get_db` crea la sesión de base de datos de la petición (la conexión se abre con la primera consulta).
2. FastAPI valida el cuerpo con `schemas.OrderCreate` (si algo no es válido responde **422**).
3. El endpoint verifica el usuario, carga todos los productos en **una sola consulta**
   `SELECT … FOR UPDATE` (bloquea las filas para evitar sobreventa), valida el stock,
   aplica el descuento, descuenta el stock y guarda el pedido con sus líneas en **un único commit**.
4. La respuesta se serializa con `schemas.OrderOut` y la sesión se cierra (si hubo error, se descarta todo).

**Modelo de datos:**

```mermaid
erDiagram
    USERS ||--o{ ORDERS : "realiza"
    ORDERS ||--|{ ORDER_ITEMS : "contiene"
    PRODUCTS ||--o{ ORDER_ITEMS : "aparece en"

    USERS {
        int id PK
        varchar(50) name
        varchar(100) email UK
    }
    PRODUCTS {
        int id PK
        varchar(100) name
        decimal price "DECIMAL(10,2)"
        int stock "CHECK stock >= 0"
    }
    ORDERS {
        int id PK
        int user_id FK
        decimal total_price "DECIMAL(10,2)"
        datetime created_at "UTC"
    }
    ORDER_ITEMS {
        int id PK
        int order_id FK
        int product_id FK
        int quantity
        decimal unit_price "DECIMAL(10,2), precio cobrado"
    }
```

## Reglas de negocio

- **Descuento:** los productos con precio **mayor a 100** tienen un **10 %** de descuento al comprarse.
  El precio unitario cobrado se redondea a centavos (`ROUND_HALF_UP`). Ejemplo: 200 → 180,00; 100 → 100,00.
- **Stock:** un pedido solo se acepta si hay stock suficiente para todos sus productos. Si no, se
  responde **409** y no se modifica nada (el pedido es atómico).
- **Concurrencia:** los productos del pedido se bloquean (`SELECT … FOR UPDATE`) mientras se procesa,
  para que dos compras simultáneas no vendan las mismas unidades.
- **Historial:** cada pedido guarda sus líneas (producto, cantidad y precio unitario cobrado), por lo que
  el historial no cambia si después cambia el precio del producto.
- **Usuarios:** el email debe ser válido y único (un duplicado responde **409**).
- **Dinero:** se guarda como `DECIMAL(10,2)` y se calcula con `Decimal`; en el JSON se expone como número.
  Un pedido cuyo total supere 99.999.999,99 (máximo de la columna) se rechaza con **422**.

## Endpoints

| Método | Ruta | Descripción | Respuestas |
|---|---|---|---|
| `POST` | `/users/` | Registra un usuario. | 201, 409 (email duplicado), 422 |
| `POST` | `/products/` | Registra un producto. | 201, 422 |
| `GET` | `/products/?limit=10&offset=0` | Lista productos paginados y ordenados por id (`limit` 1–100, por defecto 10; `offset` ≥ 0). | 200, 422 |
| `POST` | `/orders/` | Crea un pedido, aplica descuentos y descuenta stock. | 201, 404 (usuario o producto), 409 (stock), 422 (datos inválidos o total mayor a 99.999.999,99) |
| `GET` | `/users/{user_id}/orders` | Historial de pedidos del usuario con los nombres de los productos, del más reciente al más antiguo. | 200 (lista, vacía si no tiene pedidos), 404, 422 (`user_id` fuera de 1–2147483647) |

Cada endpoint tiene docstring, `summary`, `tags`, ejemplos y modelo de respuesta, visibles en `/docs`.
Formato de los errores: los de validación (422) devuelven `{"detail": [ ... ]}` con la lista de campos inválidos,
sin repetir los valores recibidos; los demás (404, 409 y el 422 por total excedido) devuelven `{"detail": "mensaje"}`.
Ante un error inesperado de base de datos, la API responde **500** con un mensaje genérico (el detalle queda en el log,
sin los datos de la consulta).

## Ejecución con Docker (recomendada)

Requisitos: Docker con Docker Compose v2.

```bash
cp .env.example .env
```

Edita `.env` y cambia las contraseñas. Usa solo letras, números, `_` y `-`: `@` y `%` rompen la URL de conexión
y Docker Compose interpreta `$` como una variable.
El archivo `.env` está en `.gitignore`: nunca se sube al repositorio.

```bash
docker compose up -d --build
```

Compose levanta MySQL 8.4, espera a que pase su *healthcheck* y luego inicia la API en <http://localhost:8000>.
Las tablas se crean automáticamente al iniciar la API. Para ver el estado y los logs:

```bash
docker compose ps
```

```bash
docker compose logs -f api
```

**Persistencia:** los datos de MySQL viven en el volumen nombrado `mysql_data` (Docker Compose lo crea como
`<nombre-del-proyecto>_mysql_data`, por ejemplo `ecommerce_api_reto_ia_grupo_aurafarmers_mysql_data`). Para comprobarlo, crea datos,
detén los contenedores **sin** `-v` y vuelve a levantarlos; los datos siguen ahí:

```bash
docker compose down
```

```bash
docker compose up -d
```

Para borrar también los datos (por ejemplo, para empezar de cero):

```bash
docker compose down -v
```

Variables de `.env`:

| Variable | Uso |
|---|---|
| `MYSQL_ROOT_PASSWORD` | Contraseña del usuario root de MySQL (solo la usa el contenedor de MySQL). |
| `MYSQL_DATABASE` | Nombre de la base de datos (por defecto `ecommerce_db`). |
| `MYSQL_USER` / `MYSQL_PASSWORD` | Usuario dedicado con el que se conecta la API (no usa root). |

## Ejecución local sin Docker

Requisitos: Python 3.12.

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

La API lee la conexión de la variable de entorno `DATABASE_URL` (si no existe, se detiene con un mensaje claro).
Para desarrollo local se puede usar SQLite:

```bash
export DATABASE_URL="sqlite:///./dev.db"
```

O un MySQL propio: `mysql+pymysql://usuario:clave@localhost:3306/ecommerce_db`.

```bash
uvicorn main:app --reload
```

## Pruebas

Las pruebas usan **SQLite en memoria**: no necesitan MySQL ni Docker.

```bash
pip install -r requirements-dev.txt
```

```bash
pytest
```

`pytest.ini` ya incluye la medición de cobertura (`pytest-cov`) sobre `main`, `database`, `models` y `schemas`,
muestra las líneas no cubiertas y **falla si la cobertura baja del 70 %** (mínimo exigido por el reto).
Resultado actual: **54 pruebas aprobadas y 97 % de cobertura**. Para ejecutar un solo archivo sin el umbral de
cobertura: `pytest tests/test_orders.py --no-cov`.

**Prueba manual de concurrencia (con Docker y MySQL real).** SQLite ignora `SELECT … FOR UPDATE`, así que el bloqueo
se comprobó a mano con el stack de Docker en ejecución. Primero, un usuario y un producto con stock 3:

```bash
curl -X POST localhost:8000/users/ -H "Content-Type: application/json" \
  -d '{"name": "Ana Pérez", "email": "ana@example.com"}'
```

```bash
curl -X POST localhost:8000/products/ -H "Content-Type: application/json" \
  -d '{"name": "Consola edición limitada", "price": 500, "stock": 3}'
```

Luego, 20 pedidos simultáneos de una unidad (usa el `id` del producto creado; aquí, 1):

```bash
seq 1 20 | xargs -P 20 -I{} curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "items": [{"product_id": 1, "quantity": 1}]}' \
  localhost:8000/orders/ | sort | uniq -c
```

Resultado obtenido con MySQL 8.4: `3 201` y `17 409`, y el stock final del producto es 0 (nunca negativo).

| Archivo | Tipo | Qué cubre |
|---|---|---|
| `tests/test_discount.py` | Unitarias | Regla del 10 %, límite exacto de 100 y redondeo. |
| `tests/test_users.py` | Integración | Registro, email duplicado y validaciones; historial de usuario inexistente o sin pedidos. |
| `tests/test_products.py` | Integración | Registro, validaciones y paginación (`limit`/`offset`). |
| `tests/test_orders.py` | Integración | Pedido con descuento y stock, ids repetidos, stock insuficiente sin efectos parciales, 404/422, límites del total, orden del historial (y desempate por id), ausencia de N+1, error de BD (500) y bloqueo `FOR UPDATE` en el dialecto MySQL. |

## Ejemplos de uso

```bash
curl -X POST localhost:8000/users/ -H "Content-Type: application/json" \
  -d '{"name": "Ana Pérez", "email": "ana@example.com"}'
```

```bash
curl -X POST localhost:8000/products/ -H "Content-Type: application/json" \
  -d '{"name": "Monitor 27", "price": 200, "stock": 5}'
```

```bash
curl -X POST localhost:8000/products/ -H "Content-Type: application/json" \
  -d '{"name": "Mouse", "price": 50, "stock": 10}'
```

```bash
curl -X POST localhost:8000/orders/ -H "Content-Type: application/json" \
  -d '{"user_id": 1, "items": [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}]}'
```

Respuesta (201): el monitor de 200 se cobra a 180 por el descuento, así que el total es 2 × 180 + 50 = 410.

```json
{
  "id": 1,
  "user_id": 1,
  "created_at": "2026-11-01T18:57:51Z",
  "total_price": 410.0,
  "items": [
    {"product_id": 1, "product_name": "Monitor 27", "quantity": 2, "unit_price": 180.0},
    {"product_id": 2, "product_name": "Mouse", "quantity": 1, "unit_price": 50.0}
  ]
}
```

```bash
curl "localhost:8000/products/?limit=10&offset=0"
```

```bash
curl localhost:8000/users/1/orders
```

## Notas

- **Cambios de contrato respecto al código original** (detalle en [`AUDITORIA.md`](AUDITORIA.md)):
  `POST /orders/` recibe `items` (producto + cantidad) en lugar de `product_ids` y devuelve el pedido completo;
  un producto inexistente responde 404 (antes 400); `GET /products/` devuelve 10 productos por defecto.
- **Esquema de base de datos:** las tablas se crean con `create_all` al iniciar la API, que **no modifica
  tablas existentes**. Si tienes una base creada con la versión original, bórrala (con Docker: `docker compose down -v`).
  En un proyecto de producción se usarían migraciones (Alembic).
- La contraseña de MySQL que estaba en el código original sigue en el historial de git: si se usó en
  algún servidor real, debe cambiarse.

## Autores

Grupo *aurafarmers* — Ingeniería de Software I, UIS:

- Juan Daniel Torres — 2240082
- Camilo Andrés Velandia — 2232728
- Santiago Fonseca — 2232737

Docente: Prof. Gabriel Pedraza Ferreira — Escuela de Ingeniería de Sistemas e Informática.
