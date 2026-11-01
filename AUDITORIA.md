# Auditoría, correcciones y registro de sugerencias de la IA

Herramienta utilizada: **Claude Code**. La auditoría inicial la hizo un sub-agente de la herramienta que recibió
el código **sin** los comentarios de pista que traía el repositorio original, para medir qué detecta por sí solo.
La columna *IA autónoma* indica si ese sub-agente detectó el problema (Sí / Parcial / No).

## 1. Problemas identificados y corregidos

| ID | Archivo / ubicación | Categoría | Problema | Corrección | IA autónoma |
|---|---|---|---|---|---|
| P01 | `database.py` | Seguridad | Credenciales en duro (`root:password123`), usuario root. | `DATABASE_URL` desde variable de entorno; `.env.example`; en Docker la API usa un usuario dedicado, no root. | Sí |
| P02 | `main.py` (`get_products`) | Rendimiento | `time.sleep(2)` en cada petición. Como el endpoint es `def`, FastAPI lo ejecuta en el *threadpool*: no bloquea el event loop, pero ocupa un hilo 2 s y puede agotar el pool (sí bloquearía el loop en un `async def`). | Eliminado. | Sí |
| P03 | `main.py` (`process_order`) | Rendimiento | Consulta N+1: un `SELECT` por producto dentro del `for`. | Una sola consulta `WHERE id IN (...)`. | Sí |
| P04 | `main.py` (`process_order`) | Regla de negocio | Descuento mal calculado (resta 10 fijos en vez del 10 %) y sin verificación de stock (stock negativo). | `apply_discount()` con `Decimal` y `ROUND_HALF_UP`; 409 si no hay stock. | Sí |
| P05 | `models.py` | Buenas prácticas / BD | Sin `unique=True` en email y sin relaciones SQLAlchemy. | Email único, columnas `NOT NULL` y relaciones `User.orders`, `Order.user`, `Order.items`, `OrderItem.product`. | Parcial (vio `unique`, no las relaciones) |
| P06 | `main.py` (`process_order`) | Regla de negocio / concurrencia | El stock se lee y se escribe sin bloqueo: dos compras simultáneas pueden vender las mismas unidades. | `SELECT … FOR UPDATE` ordenado por id y un único commit. Probado en MySQL real: 20 pedidos simultáneos contra stock 3 → 3 aceptados, 17 rechazados, stock final 0. | Sí |
| P07 | `models.py` / `main.py` | Regla de negocio | El pedido no guarda qué productos se compraron (imposible el historial). | Nueva tabla `order_items` (producto, cantidad, precio unitario cobrado). | Sí |
| P08 | `schemas.py` (`OrderCreate`) | Regla de negocio | No permite cantidades; acepta lista vacía (pedido de total 0) y listas sin límite. | `items: [{product_id, quantity}]`, entre 1 y 100 líneas; ids repetidos se suman. | Sí |
| P09 | `models.py` | Regla de negocio / BD | Dinero en `Float` (errores de redondeo). | `Numeric(10, 2)` y cálculos con `Decimal`. | Sí |
| P10 | `schemas.py` | Seguridad (validación) | Email sin validar; sin límites de longitud (nombre > 50 → error 500 en MySQL); precio y stock negativos. | `EmailStr`, longitudes iguales a la BD, precio > 0 con 2 decimales, stock ≥ 0, topes de INT. | Sí |
| P11 | `main.py` | Seguridad / estándar | Sin `response_model`: se serializan todas las columnas del ORM; creaciones con 200. | Schemas de salida `*Out` y 201 en creaciones. | Sí |
| P12 | `requirements.txt` | Seguridad | FastAPI 0.104.1 (CVE-2024-24762) y PyMySQL 1.1.0 (CVE-2024-36039); no explotables con este código, pero vulnerables. Pydantic 2.5.2 depende de `pydantic-core` 2.14.5, que no publica binarios para Python 3.13 (habría que compilarlo con Rust). | Versiones actuales fijadas y probadas. | Sí |
| P13 | `requirements.txt` | Despliegue | Falta `cryptography`: MySQL 8.4 usa `caching_sha2_password` y PyMySQL la necesita. | Agregada (verificado con MySQL 8.4 en Docker). | Parcial (marcado como dudoso) |
| P14 | `database.py` | Rendimiento | Sin `pool_pre_ping` ni `pool_recycle` (error "MySQL server has gone away" tras inactividad). | Agregados. | Sí |
| P15 | `main.py` | Estándar | `create_all` se ejecuta al importar el módulo. | Movido al `lifespan` de la aplicación. | Sí |
| P16 | `main.py` | Estándar | Sin manejo de errores: un email duplicado o un fallo de BD devuelven un 500 con traza. | 409 para email duplicado; manejador global de `SQLAlchemyError` → 500 genérico con log. | Parcial (propuso el 409, no el manejador global) |
| P17 | `models.py` | Estándar | `created_at` con hora local del servidor. | `datetime.now(timezone.utc)`; la respuesta se marca en UTC. | Sí |
| P18 | Todos | Estándar (PEP 8) | Varios imports por línea, imports sin uso, variable `U`, espacios al final, falta de líneas en blanco. | Corregido. | Sí |
| P19 | `database.py` / `models.py` / `main.py` | Estándar | API legacy de SQLAlchemy 1.x, `autocommit` obsoleto, `index=True` redundante en las PK, `db.add` redundante. | Estilo SQLAlchemy 2.0 (`DeclarativeBase`, `Mapped`, `select`). | Sí |
| P20 | `schemas.py` / `main.py` | Estándar | `ProductCreate` existía sin endpoint: no se podían crear productos por la API. | `POST /products/`. | Sí |
| P21 | `main.py` (`get_products`) | Rendimiento | Devuelve toda la tabla sin paginar. | `limit` (1–100, 10 por defecto) y `offset`, ordenado por id. | Sí |
| P22 | Proyecto | Estándar | Sin pruebas, sin docstrings/OpenAPI, sin Docker y README vacío. | Tareas 4, 5 y 6 del reto. | No (solo recibió el código) |
| P23 | `schemas.py` / `main.py` | Seguridad (validación) | *Hallado por las pruebas tras la refactorización:* los ids (`user_id`, `product_id`) no tenían límite superior; con SQLite un id mayor a 2^63-1 provocaba un 500 en texto plano. | Tope `le=2147483647` (INT de MySQL) en el cuerpo y en la ruta → 422. | Sí (sub-agente de pruebas) |
| P24 | `main.py` (`process_order`) | Regla de negocio | *Hallado por las pruebas tras la refactorización:* un total mayor a 99.999.999,99 no cabe en `DECIMAL(10,2)`; reproducido en MySQL 8.4: error 500 "Out of range value for column 'total_price'". | Se valida el total antes de modificar el stock → 422 con mensaje claro. | Sí (sub-agente de pruebas) |

## 2. Registro de sugerencias de la IA

### Aceptadas
- Todas las correcciones de la tabla anterior.
- Bloquear los productos en orden de id (`ORDER BY id … FOR UPDATE`) para reducir *deadlocks*.
- Exponer el dinero como número (`float`) en el JSON y calcular con `Decimal` (Pydantic v2 serializa `Decimal` como texto).
- Marcar las fechas como UTC en la respuesta (MySQL `DATETIME` no guarda zona horaria).
- Tope `le=2147483647` en `stock` y `quantity` para responder 422 en vez de un error 500 de MySQL.
- Reutilizar la misma consulta de carga (`selectinload`) en la creación de pedidos y en el historial.
- Forzar `DATABASE_URL=sqlite://` en las pruebas para que nunca toquen una base real.
- Probar el bloqueo `FOR UPDATE` capturando la consulta que el endpoint ejecuta de verdad (y no una copia).

### Rechazadas
| Sugerencia | Motivo |
|---|---|
| Autenticación JWT y tomar el usuario del token (en vez de `user_id`). | Fuera del alcance del reto y cambiaría el contrato pedido (`/users/{user_id}/orders`). Queda como mejora futura. |
| Migraciones con Alembic. | Sobreingeniería para el reto; se dejó `create_all` en el `lifespan` y se documentó su limitación en el README. |
| `pool_size` / `max_overflow` explícitos. | Los valores por defecto bastan para este proyecto. |
| Ampliar el email a 254 caracteres. | Se mantuvo 100, alineado entre BD y validación. |
| `charset=utf8mb4` explícito en la URL. | MySQL 8.4 y PyMySQL ya usan `utf8mb4` por defecto (verificado con `SHOW CREATE TABLE`). |
| Lock de dependencias, `pip-audit` y `ruff` en CI. | Útiles, pero fuera del alcance del reto. |
| Reescribir el historial de git para borrar la contraseña. | Riesgoso y desproporcionado; se recomienda rotar la contraseña. |
| Comprobar el email con una consulta antes de insertar. | Redundante: capturar `IntegrityError` cubre también el caso concurrente. |

### Corregidas manualmente (la sugerencia inicial era incorrecta u obsoleta)
- El comentario del código original sugería `datetime.utcnow`, que está **deprecado desde Python 3.12**: se usó `datetime.now(timezone.utc)`.
- La primera versión del plan mezclaba `Decimal` con `float` en el descuento (`TypeError`) y usaba `round()` (redondeo bancario): se corrigió a `Decimal("0.90")` con `ROUND_HALF_UP`.
- Las instrucciones iniciales de pruebas usaban `httpx`, que Starlette 1.10 ya depreca para `TestClient`: se cambió a `httpx2`.
- La IA indicó filtrar en `pytest.ini` un aviso de SQLAlchemy sobre `Decimal` en SQLite que ya no existe en SQLAlchemy 2.0.55: se eliminó el filtro.

## 3. Cambios de contrato respecto al código original

| Endpoint | Antes | Ahora |
|---|---|---|
| `POST /orders/` (petición) | `{"user_id": 1, "product_ids": [1, 1, 2]}` | `{"user_id": 1, "items": [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}]}` |
| `POST /orders/` (respuesta) | `{"status": "ok", "order_id": 1, "total": 430}` con 200 (con precios 200 y 50: cobro incorrecto) | Pedido completo (`id`, `user_id`, `created_at`, `total_price`: 410.0, `items[]`) con 201 |
| `POST /orders/` producto inexistente | 400 | 404 |
| `POST /users/` | 200 y el objeto ORM | 201 con `{id, name, email}`; 409 si el email existe |
| `GET /products/` | Todos los productos (con 2 s de espera) | 10 por defecto, paginado con `limit`/`offset` |
