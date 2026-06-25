"""oauth_creds.py — Credenciales OAuth de la cuenta del estudio (Drive + Calendar).

La cuenta de servicio NO tiene espacio propio en Drive y, en Gmail gratis, no hay
Unidades Compartidas. Por eso los adjuntos (Drive) y el calendario (Calendar) se
acceden actuando COMO la cuenta del estudio, vía OAuth con un refresh token de
larga duración (generado una sola vez con gen_oauth_token.py).

Config (mismas claves en st.secrets o en .env, en mayúsculas):
  oauth_client_id      / OAUTH_CLIENT_ID
  oauth_client_secret  / OAUTH_CLIENT_SECRET
  oauth_refresh_token  / OAUTH_REFRESH_TOKEN

IMPORTANTE (performance): Drive/Calendar se llaman vía HTTP directo con `requests`
(sesión persistente con keep-alive), NO con googleapiclient/httplib2 — httplib2 se
colgaba/relentizaba muchísimo con estas credenciales OAuth. Acá solo resolvemos el
**access token** (refrescándolo cuando vence) y exponemos una `requests.Session`
compartida. Si falta config, disponible()=False y la app degrada con elegancia.
"""

from __future__ import annotations

import threading

import requests
from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import Request as GoogleAuthRequest

import casos_db  # reutilizamos su lector de .env

OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar.events",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"

_lock = threading.Lock()
_token_lock = threading.Lock()
_creds = None
_session = None


def _leer_config():
    """Devuelve (client_id, client_secret, refresh_token) o (None, None, None)."""
    # 1) Streamlit secrets
    try:
        import streamlit as st
        cid = st.secrets.get("oauth_client_id")
        csec = st.secrets.get("oauth_client_secret")
        rtok = st.secrets.get("oauth_refresh_token")
        if cid and csec and rtok:
            return str(cid), str(csec), str(rtok)
    except Exception:
        pass
    # 2) .env / entorno
    env = casos_db._env_combinado()
    cid = env.get("OAUTH_CLIENT_ID")
    csec = env.get("OAUTH_CLIENT_SECRET")
    rtok = env.get("OAUTH_REFRESH_TOKEN")
    if cid and csec and rtok:
        return cid, csec, rtok
    return None, None, None


def disponible() -> bool:
    """True si hay credenciales OAuth configuradas (para mensajes en la UI)."""
    cid, csec, rtok = _leer_config()
    return bool(cid and csec and rtok)


def get_session() -> requests.Session:
    """Sesión `requests` compartida (keep-alive: reusa la conexión TLS → rápido)."""
    global _session
    if _session is not None:
        return _session
    with _lock:
        if _session is None:
            s = requests.Session()
            s.headers.update({"User-Agent": "gestor-casos/1.0"})
            _session = s
        return _session


def _get_creds():
    global _creds
    if _creds is not None:
        return _creds
    with _lock:
        if _creds is not None:
            return _creds
        cid, csec, rtok = _leer_config()
        if not (cid and csec and rtok):
            raise RuntimeError(
                "Faltan credenciales OAuth (oauth_client_id / oauth_client_secret / "
                "oauth_refresh_token en secrets o .env). Generalas con gen_oauth_token.py."
            )
        _creds = UserCredentials(
            token=None,
            refresh_token=rtok,
            client_id=cid,
            client_secret=csec,
            token_uri=TOKEN_URI,
            scopes=OAUTH_SCOPES,
        )
        return _creds


def get_access_token() -> str:
    """Devuelve un access token válido (lo refresca solo cuando vence ~1h).

    El refresh usa transporte `requests` sobre la sesión compartida (rápido).
    """
    creds = _get_creds()
    with _token_lock:
        if not creds.valid:
            creds.refresh(GoogleAuthRequest(session=get_session()))
        return creds.token


def auth_header() -> dict:
    return {"Authorization": f"Bearer {get_access_token()}"}


def reset():
    """Descarta credenciales/sesión cacheadas (token rotado / conexión muerta)."""
    global _creds, _session
    with _lock:
        _creds = None
        if _session is not None:
            try:
                _session.close()
            except Exception:
                pass
        _session = None
