from sqlalchemy.orm import DeclarativeBase, declared_attr
from sqlalchemy import MetaData

# Naming convention for Alembic
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=convention)


class Base(DeclarativeBase):
    metadata = metadata

    @declared_attr.directive
    def __tablename__(cls) -> str:  # type: ignore
        # Convert CamelCase to snake_case plural? We'll define explicit table names in models
        return cls.__name__.lower()
