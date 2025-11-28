from schemas.auth import LoginRequest
from fastapi import APIRouter
from passlib.hash import bcrypt  
from sqlalchemy.orm import Session
from deps import create_access_token
from fastapi import Depends, HTTPException, status
from db.init_db import get_db
from Models import User

router = APIRouter()

# Auth routes
@router.post("/login")
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    username = payload.username
    password = payload.password
    user = db.query(User).filter(User.username == username).first()
    if not user:  # In production, use proper password hashing
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    if not bcrypt.verify(password, user.pw_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    return {"access_token": create_access_token(user.id)}

