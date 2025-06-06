from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from db.models import Base
from settings import get_settings

settings = get_settings()

def init_db():
    engine = create_engine(settings.postgres_url)
    
    # Create pgvector extension
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()
    
    # Create all tables
    Base.metadata.create_all(engine)
    
    return sessionmaker(bind=engine)()

def get_db():
    """Dependency for FastAPI endpoints"""
    db = init_db()
    try:
        yield db
    finally:
        db.close() 