from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from settings import get_settings


settings = get_settings()


engine = create_engine(
    settings.postgres_url,
    pool_pre_ping=True,  # auto-check dead connections
    future=True
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True
)


def get_db():
    """
    Used in FastAPI routes:
    db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session():
    """
    Used in scripts:
        with db_session() as db:
            db.query(...)
            db.add(...)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()