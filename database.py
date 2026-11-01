import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "La variable de entorno DATABASE_URL no está definida. "
        "Defínela antes de iniciar la aplicación (consulta .env.example), "
        "por ejemplo: "
        "mysql+pymysql://usuario:clave@localhost:3306/ecommerce_db"
    )

# pool_pre_ping descarta conexiones caídas y pool_recycle las renueva antes
# de que MySQL las cierre por inactividad (wait_timeout). hide_parameters
# evita que los datos de los usuarios queden en los logs de error.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    hide_parameters=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    """Clase base de la que heredan todos los modelos ORM."""


def get_db() -> Iterator[Session]:
    """Entrega una sesión de base de datos por petición y la cierra al final.

    Al cerrarse, la sesión descarta (rollback) cualquier transacción que no
    se haya confirmado con commit.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
