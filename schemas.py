from datetime import datetime
from datetime import timezone
from decimal import Decimal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import EmailStr
from pydantic import Field
from pydantic import field_validator


# Los montos de dinero se reciben como Decimal (exactitud en los cálculos),
# pero se exponen como float: Pydantic v2 serializa Decimal como texto en
# JSON y los clientes esperan números.

# Valor máximo de una columna INT en MySQL: evita un error 500 de la base de
# datos cuando se envían ids o cantidades fuera de rango (se responde 422).
MAX_INT = 2_147_483_647


class UserCreate(BaseModel):
    """Datos para registrar un usuario."""

    # Quita espacios al inicio y al final: un nombre de solo espacios queda
    # vacío y min_length lo rechaza.
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        min_length=1,
        max_length=50,
        description="Nombre del usuario.",
        examples=["Ana Pérez"],
    )
    email: EmailStr = Field(
        max_length=100,
        description=(
            "Correo electrónico del usuario. Debe ser único y se guarda en "
            "minúsculas."
        ),
        examples=["ana.perez@example.com"],
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Pasa el email a minúsculas.

        Así la unicidad no depende de mayúsculas: MySQL ya las ignora al
        comparar, pero SQLite no.
        """
        return value.lower()


class ProductCreate(BaseModel):
    """Datos para registrar un producto en el catálogo."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Nombre del producto.",
        examples=["Teclado mecánico"],
    )
    price: Decimal = Field(
        gt=0,
        max_digits=10,
        decimal_places=2,
        description="Precio unitario, mayor que 0 y con máximo 2 decimales.",
        examples=[199.99],
    )
    stock: int = Field(
        ge=0,
        le=MAX_INT,
        description="Unidades disponibles en inventario.",
        examples=[25],
    )


class OrderItemCreate(BaseModel):
    """Producto y cantidad solicitados dentro de un pedido."""

    product_id: int = Field(
        gt=0,
        le=MAX_INT,
        description="Identificador del producto.",
        examples=[1],
    )
    quantity: int = Field(
        default=1,
        ge=1,
        le=MAX_INT,
        description="Unidades solicitadas (por defecto 1).",
        examples=[2],
    )


class OrderCreate(BaseModel):
    """Datos para crear un pedido."""

    user_id: int = Field(
        gt=0,
        le=MAX_INT,
        description="Identificador del usuario que realiza el pedido.",
        examples=[1],
    )
    items: list[OrderItemCreate] = Field(
        min_length=1,
        max_length=100,
        description=(
            "Productos del pedido (entre 1 y 100 líneas). Si un producto se "
            "repite, sus cantidades se suman."
        ),
        examples=[
            [
                {"product_id": 1, "quantity": 2},
                {"product_id": 2, "quantity": 1},
            ]
        ],
    )


class UserOut(BaseModel):
    """Usuario registrado."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Identificador del usuario.", examples=[1])
    name: str = Field(
        description="Nombre del usuario.",
        examples=["Ana Pérez"],
    )
    email: str = Field(
        description="Correo electrónico del usuario.",
        examples=["ana.perez@example.com"],
    )


class ProductOut(BaseModel):
    """Producto del catálogo."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Identificador del producto.", examples=[1])
    name: str = Field(
        description="Nombre del producto.",
        examples=["Teclado mecánico"],
    )
    price: float = Field(
        description="Precio unitario de lista (sin descuento).",
        examples=[199.99],
    )
    stock: int = Field(
        description="Unidades disponibles en inventario.",
        examples=[25],
    )


class OrderItemOut(BaseModel):
    """Línea de un pedido con el precio unitario cobrado."""

    model_config = ConfigDict(from_attributes=True)

    product_id: int = Field(
        description="Identificador del producto.",
        examples=[1],
    )
    product_name: str = Field(
        description="Nombre del producto.",
        examples=["Teclado mecánico"],
    )
    quantity: int = Field(description="Unidades compradas.", examples=[2])
    unit_price: float = Field(
        description="Precio unitario cobrado, con el descuento ya aplicado.",
        examples=[179.99],
    )


class OrderOut(BaseModel):
    """Pedido con sus líneas y el total cobrado."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Identificador del pedido.", examples=[1])
    user_id: int = Field(
        description="Identificador del usuario que hizo el pedido.",
        examples=[1],
    )
    created_at: datetime = Field(
        description="Fecha y hora de creación del pedido (UTC).",
        examples=["2025-01-15T14:30:00Z"],
    )
    total_price: float = Field(
        description="Total cobrado: suma de precio unitario por cantidad.",
        examples=[409.98],
    )
    items: list[OrderItemOut] = Field(description="Líneas del pedido.")

    @field_validator("created_at")
    @classmethod
    def assume_utc(cls, value: datetime) -> datetime:
        """Marca como UTC las fechas que la base de datos devuelve sin zona.

        MySQL (DATETIME) y SQLite no guardan la zona horaria, así que al leer
        el pedido la fecha llega sin ella aunque se haya guardado en UTC.
        """
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
