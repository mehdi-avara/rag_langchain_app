from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from db.models import User
from db.init_db import get_db
from settings import get_settings

settings = get_settings()
security = HTTPBearer()

def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=settings.jwt_exp_hours)
    to_encode = {"sub": str(user_id), "exp": expire}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
        
    return user 