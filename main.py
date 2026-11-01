import logging
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import ROUND_HALF_UP
from decimal import Decimal
from typing import Annotated

from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Path
from fastapi import Query
from fastapi import Request
from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

import database
import models
import schemas


logger = logging.getLogger(__name__)

DISCOUNT_THRESHOLD = Decimal("100")
DISCOUNT_FACTOR = Decimal("0.90")
CENTS = Decimal("0.01")

DbSession = Annotated[Session, Depends(database.get_db)]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Crea las tablas que falten al iniciar la aplicación."""
    models.Base.metadata.create_all(bind=database.engine)
    yield


app = FastAPI(
    title="API de E-commerce",
    description=(
        "API REST para gestionar usuarios, el catálogo de productos y los "
        "pedidos de una tienda en línea. Los productos con precio mayor a "
        "100 tienen un 10 % de descuento al comprarse."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    """Registra el error de base de datos y responde 500 sin exponer detalles.

    La sesión se descarta (rollback) en get_db al propagarse la excepción.
    """
    logger.error(
        "Error de base de datos en %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Error interno de base de datos"},
    )


def apply_discount(price: Decimal) -> Decimal:
    """Devuelve el precio unitario a cobrar, redondeado a centavos.

    Si el precio es mayor a DISCOUNT_THRESHOLD se aplica un 10 % de
    descuento (DISCOUNT_FACTOR); si no, se cobra el precio de lista.
    """
    if price > DISCOUNT_THRESHOLD:
        price = price * DISCOUNT_FACTOR
    return price.quantize(CENTS, rounding=ROUND_HALF_UP)


def select_orders_with_items() -> Select[tuple[models.Order]]:
    """Consulta de pedidos que carga sus líneas y productos sin N+1."""
    return select(models.Order).options(
        selectinload(models.Order.items).selectinload(models.OrderItem.product)
    )


@app.post(
    "/users/",
    response_model=schemas.UserOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Usuarios"],
    summary="Registrar un usuario",
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "Ya existe un usuario con ese email",
        },
    },
)
def create_user(user: schemas.UserCreate, db: DbSession) -> models.User:
    """Registra un usuario nuevo y lo devuelve con su identificador.

    Reglas:
    - El nombre debe tener entre 1 y 50 caracteres.
    - El email debe ser válido, tener máximo 100 caracteres y ser único.

    Errores:
    - **409**: ya existe un usuario registrado con ese email.
    - **422**: los datos enviados no son válidos.
    """
    new_user = models.User(name=user.name, email=user.email)
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un usuario con ese email",
        ) from exc
    db.refresh(new_user)
    return new_user


@app.post(
    "/products/",
    response_model=schemas.ProductOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Productos"],
    summary="Registrar un producto",
)
def create_product(
    product: schemas.ProductCreate, db: DbSession
) -> models.Product:
    """Agrega un producto al catálogo y lo devuelve con su identificador.

    Reglas:
    - El precio debe ser mayor que 0 y tener máximo 2 decimales.
    - El stock no puede ser negativo.

    Errores:
    - **422**: los datos enviados no son válidos.
    """
    new_product = models.Product(
        name=product.name,
        price=product.price,
        stock=product.stock,
    )
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product


@app.get(
    "/products/",
    response_model=list[schemas.ProductOut],
    status_code=status.HTTP_200_OK,
    tags=["Productos"],
    summary="Listar productos",
)
def get_products(
    db: DbSession,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Cantidad máxima de productos."),
    ] = 10,
    offset: Annotated[
        int,
        Query(ge=0, description="Cantidad de productos a omitir."),
    ] = 0,
) -> list[models.Product]:
    """Lista los productos del catálogo de forma paginada.

    Reglas:
    - Los productos se devuelven ordenados por identificador.
    - `limit` va de 1 a 100 (por defecto 10) y `offset` desde 0.
    - El precio mostrado es el de lista, sin descuento.

    Errores:
    - **422**: `limit` u `offset` fuera de rango.
    """
    stmt = (
        select(models.Product)
        .order_by(models.Product.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))


@app.post(
    "/orders/",
    response_model=schemas.OrderOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Pedidos"],
    summary="Crear un pedido",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "El usuario o alguno de los productos no existe",
        },
        status.HTTP_409_CONFLICT: {
            "description": "Stock insuficiente para algún producto",
        },
    },
)
def process_order(order: schemas.OrderCreate, db: DbSession) -> models.Order:
    """Crea un pedido, descuenta el stock y devuelve el pedido con su total.

    Reglas:
    - Si un producto aparece varias veces, sus cantidades se suman.
    - Los productos con precio mayor a 100 tienen un 10 % de descuento; el
      precio unitario cobrado se redondea a centavos.
    - El total es la suma de precio unitario cobrado por cantidad.
    - El pedido es atómico: si algo falla no se guarda nada ni se descuenta
      stock. Los productos se bloquean mientras se procesa el pedido para
      que dos compras simultáneas no vendan el mismo stock.

    Errores:
    - **404**: el usuario no existe o hay productos inexistentes (se indican
      sus identificadores).
    - **409**: no hay stock suficiente (se indica el producto, lo disponible
      y lo solicitado).
    - **422**: los datos enviados no son válidos.
    """
    if db.get(models.User, order.user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )

    quantities: Counter[int] = Counter()
    for item in order.items:
        quantities[item.product_id] += item.quantity

    stmt = (
        select(models.Product)
        .where(models.Product.id.in_(list(quantities)))
        .order_by(models.Product.id)
        .with_for_update()
    )
    products = {product.id: product for product in db.scalars(stmt)}

    missing_ids = sorted(set(quantities) - set(products))
    if missing_ids:
        missing = ", ".join(str(product_id) for product_id in missing_ids)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Productos no encontrados: {missing}",
        )

    for product_id, quantity in quantities.items():
        product = products[product_id]
        if product.stock < quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Stock insuficiente para el producto '{product.name}' "
                    f"(id {product.id}): disponible {product.stock}, "
                    f"solicitado {quantity}"
                ),
            )

    items = []
    for product_id, quantity in quantities.items():
        product = products[product_id]
        product.stock -= quantity
        items.append(
            models.OrderItem(
                product=product,
                quantity=quantity,
                unit_price=apply_discount(product.price),
            )
        )
    total = sum(
        (item.unit_price * item.quantity for item in items),
        Decimal("0.00"),
    )
    new_order = models.Order(
        user_id=order.user_id,
        total_price=total,
        items=items,
    )
    db.add(new_order)
    db.commit()

    stmt = select_orders_with_items().where(models.Order.id == new_order.id)
    return db.scalars(stmt).one()


@app.get(
    "/users/{user_id}/orders",
    response_model=list[schemas.OrderOut],
    status_code=status.HTTP_200_OK,
    tags=["Pedidos"],
    summary="Historial de pedidos de un usuario",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Usuario no encontrado"},
    },
)
def get_user_orders(
    user_id: Annotated[int, Path(description="Identificador del usuario.")],
    db: DbSession,
) -> list[models.Order]:
    """Devuelve los pedidos de un usuario con sus productos.

    Reglas:
    - Los pedidos se ordenan del más reciente al más antiguo.
    - Cada línea incluye el nombre del producto, la cantidad y el precio
      unitario cobrado.
    - Si el usuario no tiene pedidos se devuelve una lista vacía.

    Errores:
    - **404**: el usuario no existe.
    """
    if db.get(models.User, user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )

    stmt = (
        select_orders_with_items()
        .where(models.Order.user_id == user_id)
        .order_by(models.Order.created_at.desc(), models.Order.id.desc())
    )
    return list(db.scalars(stmt))
