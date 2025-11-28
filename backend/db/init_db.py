from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from passlib.hash import bcrypt  

from db.base import Base
from Models import User
from settings import get_settings

settings = get_settings()

def init_db():
    engine = create_engine(settings.postgres_url,pool_pre_ping=True)

    # Create pgvector extension
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()
        
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Add default user if not exists
    default_username = settings.default_username
    default_password = settings.default_password

    user = db.query(User).filter_by(username=default_username).first()
    if not user:
        hashed_pw = bcrypt.hash(default_password)
        user = User(username=default_username, pw_hash=hashed_pw, role="admin")
        db.add(user)
        db.commit()

    return db

def get_db():
    """Dependency for FastAPI endpoints"""
    db = init_db()
    try:
        yield db
    finally:
        db.close() 