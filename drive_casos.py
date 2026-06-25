"""drive_casos.py — Subida de adjuntos a Google Drive (vía OAuth del estudio).

Subimos actuando COMO la cuenta del estudio (oauth_creds), porque en Gmail gratis
la cuenta de servicio no tiene cuota ni hay Unidades Compartidas. Los archivos
quedan en el Drive del estudio (15 GB) y se comparten "cualquiera con el link
puede ver" para poder mostrarlos en la app.

PERFORMANCE: usamos HTTP directo con `requests` (sesión persistente de oauth_creds)
en vez de googleapiclient/httplib2, que se colgaba/relentizaba con OAuth. Una
subida chica = 1 request (multipart) + 1 request (permiso). Destino opcional:
carpeta `drive_folder_id` (secrets) / DRIVE_FOLDER_ID (.env); si no, raíz de Mi unidad.
"""

from __future__ import annotations

import json
import threading

import requests

import casos_db
import oauth_creds

_lock = threading.Lock()
_folder_id_cache = None
_FOLDER_SENTINEL = object()

_UPLOAD_URL = ("https://www.googleapis.com/upload/drive/v3/files"
               "?uploadType=multipart&fields=id,webViewLink&supportsAllDrives=true")
_PERM_URL = "https://www.googleapis.com/drive/v3/files/{fid}/permissions?supportsAllDrives=true"

_TIMEOUT = (10, 120)  # (conexión, lectura) en segundos


def _folder_id():
    """ID de carpeta destino (opcional). '' si no hay (va a la raíz)."""
    global _folder_id_cache
    if _folder_id_cache is not _FOLDER_SENTINEL and _folder_id_cache is not None:
        return _folder_id_cache
    fid = ""
    try:
        import streamlit as st
        fid = st.secrets.get("drive_folder_id") or ""
    except Exception:
        fid = ""
    if not fid:
        fid = casos_db._env_combinado().get("DRIVE_FOLDER_ID", "")
    _folder_id_cache = fid
    return fid


def disponible() -> bool:
    """True si hay credenciales OAuth para subir (para mensajes en la UI)."""
    return oauth_creds.disponible()


def _slug(s: str) -> str:
    keep = [c if (c.isalnum() or c in " -_.") else "_" for c in (s or "").strip()]
    return ("".join(keep).strip().replace(" ", "_")) or "x"


def _intentar_subida(file_bytes: bytes, nombre: str, mimetype) -> dict:
    """Sube el archivo (multipart) y lo comparte 'anyone:reader'. Devuelve el JSON."""
    sess = oauth_creds.get_session()
    token = oauth_creds.get_access_token()
    mimetype = mimetype or "application/octet-stream"

    metadata = {"name": nombre}
    fid = _folder_id()
    if fid:
        metadata["parents"] = [fid]

    # Cuerpo multipart/related: parte 1 = metadata JSON, parte 2 = bytes del archivo.
    boundary = "===============gestor-casos-boundary=="
    pre = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mimetype}\r\n\r\n"
    ).encode("utf-8")
    post = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = pre + file_bytes + post

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/related; boundary={boundary}",
    }
    r = sess.post(_UPLOAD_URL, headers=headers, data=body, timeout=_TIMEOUT)
    r.raise_for_status()
    archivo = r.json()

    # Compartir: cualquiera con el link puede ver.
    r2 = sess.post(
        _PERM_URL.format(fid=archivo["id"]),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        data=json.dumps({"type": "anyone", "role": "reader"}),
        timeout=_TIMEOUT,
    )
    r2.raise_for_status()
    return archivo


def subir_adjunto(file_bytes: bytes, filename: str, mimetype: str | None = None,
                  prefijo: str = "") -> str:
    """Sube un archivo al Drive del estudio y devuelve su link (webViewLink).

    Reintenta (reseteando credenciales/sesión) si la conexión se cae.
    """
    nombre = f"{_slug(prefijo)}__{filename}" if prefijo else filename
    ultimo_error: Exception | None = None
    for _intento in range(3):
        try:
            with _lock:
                archivo = _intentar_subida(file_bytes, nombre, mimetype)
            return (archivo.get("webViewLink")
                    or f"https://drive.google.com/file/d/{archivo['id']}/view")
        except requests.RequestException as e:
            ultimo_error = e
            oauth_creds.reset()  # conexión muerta / token vencido → reconstruir
    raise RuntimeError(
        "No pude subir el archivo a Drive tras varios intentos "
        f"(conexión inestable). Probá de nuevo. Detalle: {ultimo_error}"
    )
