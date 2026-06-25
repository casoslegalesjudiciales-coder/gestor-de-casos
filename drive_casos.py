"""drive_casos.py — Subida de adjuntos a Google Drive (vía OAuth del estudio).

A diferencia del template de facturas (que usaba la cuenta de servicio + Unidad
Compartida), acá subimos actuando COMO la cuenta del estudio (oauth_creds), porque
en Gmail gratis la SA no tiene cuota ni hay Unidades Compartidas. Los archivos
quedan en el Drive del estudio (15 GB) y se comparten "cualquiera con el link
puede ver" para poder mostrarlos en la app.

Destino opcional: una carpeta normal del Drive del estudio cuyo ID se ponga en
`drive_folder_id` (secrets) / DRIVE_FOLDER_ID (.env). Si no se define, van a la
raíz de "Mi unidad".
"""

from __future__ import annotations

import io
import threading

from googleapiclient.http import MediaIoBaseUpload

import casos_db
import oauth_creds

_lock = threading.Lock()
_folder_id_cache = None
_FOLDER_SENTINEL = object()

_ERRORES_RED = (
    BrokenPipeError, ConnectionError, ConnectionResetError,
    ConnectionAbortedError, TimeoutError, OSError,
)


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


def _intentar_subida(file_bytes: bytes, nombre: str, mimetype):
    svc = oauth_creds.get_drive_service()
    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes),
        mimetype=mimetype or "application/octet-stream",
        resumable=True,
        chunksize=5 * 1024 * 1024,
    )
    body = {"name": nombre}
    fid = _folder_id()
    if fid:
        body["parents"] = [fid]
    req = svc.files().create(body=body, media_body=media, fields="id, webViewLink")
    archivo = None
    while archivo is None:
        _status, archivo = req.next_chunk(num_retries=3)
    svc.permissions().create(
        fileId=archivo["id"],
        body={"type": "anyone", "role": "reader"},
        fields="id",
    ).execute(num_retries=3)
    return archivo


def subir_adjunto(file_bytes: bytes, filename: str, mimetype: str | None = None,
                  prefijo: str = "") -> str:
    """Sube un archivo al Drive del estudio y devuelve su link (webViewLink).

    Reintenta reconstruyendo la conexión si se cae (Broken pipe / reset).
    """
    nombre = f"{_slug(prefijo)}__{filename}" if prefijo else filename
    ultimo_error: Exception | None = None
    for _intento in range(3):
        try:
            with _lock:
                archivo = _intentar_subida(file_bytes, nombre, mimetype)
            return (archivo.get("webViewLink")
                    or f"https://drive.google.com/file/d/{archivo['id']}/view")
        except _ERRORES_RED as e:
            ultimo_error = e
            oauth_creds.reset()
    raise RuntimeError(
        "No pude subir el archivo a Drive tras varios intentos "
        f"(conexión inestable). Probá de nuevo. Detalle: {ultimo_error}"
    )
