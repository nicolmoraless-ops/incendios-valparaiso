"""Autenticación JWT (HS256) y autorización por roles (RBAC)."""
import datetime as dt
import os

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from . import db

SECRET = os.environ["JWT_SECRET"]
ALG = "HS256"
EXP_MIN = int(os.getenv("JWT_EXP_MIN", "30"))

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def seed_usuarios():
    """Crea los usuarios de demostración a partir de secretos (nunca contraseñas en el código)."""
    usuarios = {
        "admin": (os.environ["ADMIN_PASSWORD"], "admin"),
        "analista": (os.environ["ANALISTA_PASSWORD"], "analista"),
    }
    with db.conn() as c:
        for nombre, (clave, rol) in usuarios.items():
            h = bcrypt.hashpw(clave.encode(), bcrypt.gensalt(rounds=12)).decode()
            c.execute(
                "INSERT INTO usuarios (usuario, hash, rol) VALUES (%s, %s, %s) ON CONFLICT (usuario) DO NOTHING",
                (nombre, h, rol),
            )


def autenticar(usuario: str, clave: str):
    with db.conn() as c:
        fila = c.execute("SELECT usuario, hash, rol FROM usuarios WHERE usuario = %s", (usuario,)).fetchone()
    if not fila or not bcrypt.checkpw(clave.encode(), fila["hash"].encode()):
        return None
    return fila


def crear_token(usuario: str, rol: str) -> str:
    ahora = dt.datetime.now(dt.timezone.utc)
    datos = {"sub": usuario, "rol": rol, "iat": ahora, "exp": ahora + dt.timedelta(minutes=EXP_MIN)}
    return jwt.encode(datos, SECRET, algorithm=ALG)


def usuario_actual(token: str = Depends(oauth2)) -> dict:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALG])
    except jwt.PyJWTError:
        raise HTTPException(401, "Token inválido o expirado", headers={"WWW-Authenticate": "Bearer"})


def requiere_rol(*roles: str):
    def verificar(u: dict = Depends(usuario_actual)) -> dict:
        if u.get("rol") not in roles:
            raise HTTPException(403, "El rol no tiene permiso para esta operación")
        return u
    return verificar
