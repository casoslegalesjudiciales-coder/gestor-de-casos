"""oauth_creds.py — Credenciales OAuth de la cuenta del estudio (Drive + Calendar).

La cuenta de servicio NO tiene espacio propio en Drive y, en Gmail gratis, no hay
Unidades Compartidas. Por eso los adjuntos (Drive) y el calendario (Calendar) se
acceden actuando COMO la cuenta del estudio, vía OAuth con un refresh token de
larga duración (generado una sola vez con gen_oauth_token.py).

Config (mismas claves en st.secrets o en .env, en mayúsculas):
  oauth_client_id      / OAUTH_CLIENT_ID
  oauth_client_secret  / OAUTH_CLIENT_SECRET
  oauth_refresh_token  / OAUTH_REFRESH_TOKEN

Un solo consentimiento cubre ambos scopes. Si falta algo, disponible()=False y la
app degrada con elegancia (sigue funcionando casos/agenda/semáforo/.ics).
"""

from __future__ import annotations

import threading

from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build

import casos_db  # reutilizamos su lector de .env

OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar.events",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"

_lock = threading.Lock()
_creds = None
_drive = None
_calendar = None


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


def reset():
    """Descarta credenciales y servicios cacheados (conexión muerta / token rotado)."""
    global _creds, _drive, _calendar
    with _lock:
        _creds = None
        _drive = None
        _calendar = None


def get_drive_service():
    global _drive
    if _drive is not None:
        return _drive
    with _lock:
        if _drive is None:
            _drive = build("drive", "v3", credentials=_get_creds(), cache_discovery=False)
        return _drive


def get_calendar_service():
    global _calendar
    if _calendar is not None:
        return _calendar
    with _lock:
        if _calendar is None:
            _calendar = build("calendar", "v3", credentials=_get_creds(), cache_discovery=False)
        return _calendar
