"""casos_db.py — Capa de datos sobre Google Sheets para el Gestor de Casos.

Base de datos COMPARTIDA: todas las personas del estudio leen/escriben el mismo
Google Sheet. Tres pestañas:

  • Casos     — un caso por fila (tabla ANCHA; el formulario muestra sólo el
                subset de columnas del área). Ver CASOS_HEADERS.
  • Agenda    — eventos (audiencias / plazos / recordatorios). Fuente del
                semáforo y del calendario. Ver AGENDA_HEADERS.
  • Adjuntos  — archivos en Drive (telegramas, dictámenes, fotos, etc.), N por
                caso. Ver ADJUNTOS_HEADERS.

Credenciales: SOLO Service Account para Sheets (no sube archivos → no necesita
cuota de Drive). El Sheet lo posee la cuenta del estudio y se comparte con la SA
como Editor. Resolución, en orden:
  1. st.secrets["gcp_service_account"] + st.secrets["sheets_id"]   (Streamlit Cloud)
  2. .env / entorno:  GOOGLE_SA_PATH  +  CASOS_SHEETS_ID

Patrón adaptado de tools/facturas_app/sheet_db.py (probado en producción).
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Sheets solamente: los adjuntos van por OAuth (drive_casos.py), no por la SA.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HOJA_CASOS = "Casos"
HOJA_AGENDA = "Agenda"
HOJA_ADJUNTOS = "Adjuntos"

# --- Casos: tabla ancha (33 columnas, A:AG). El orden importa (es el del Sheet).
CASOS_HEADERS = [
    "id", "rubro", "area", "cliente", "estado_caso",          # A–E
    "empresa", "seguro", "diagnostico", "descripcion",        # F–I
    "fecha_despido", "fecha_accidente", "fecha_alta_o_rechazo",
    "fecha_inicio_comisiones", "fecha_pericia",               # J–N
    "danos_materiales", "hay_lesiones",                       # O–P
    "hubo_acuerdo", "monto_acuerdo", "forma_pago", "fecha_acuerdo",
    "dictamen_texto",                                         # Q–U
    "expediente", "juzgado", "fecha_inicio_demanda",
    "fecha_traslado_demanda", "fecha_contestacion_demanda",   # V–Z
    "fecha_traba_litis", "fecha_examen_medico",
    "fecha_audiencia_art80", "fecha_audiencia_testimonial",   # AA–AD
    "fecha_sentencia", "sentencia_texto",                     # AE–AF
    "creado_ts",                                              # AG
]
RANGO_CASOS = "A:AG"

# --- Agenda: eventos (A:I). gcal_event_id permite editar/borrar en Calendar.
AGENDA_HEADERS = [
    "id", "caso_id", "tipo", "descripcion", "fecha",
    "recordar_dias", "estado", "creado_ts", "gcal_event_id",
]
RANGO_AGENDA = "A:I"

# --- Adjuntos: archivos en Drive (A:G).
ADJUNTOS_HEADERS = [
    "id", "caso_id", "tipo", "descripcion", "fecha", "url", "creado_ts",
]
RANGO_ADJUNTOS = "A:G"

ESTADO_EVENTO_PENDIENTE = "Pendiente"
ESTADO_EVENTO_CUMPLIDO = "Cumplido"

CACHE_TTL = 120


# ----- Resolución de credenciales --------------------------------------------

_service = None
_service_lock = threading.Lock()
_sheet_id_cached = None


def _read_dotenv(path: str) -> dict:
    """Parser mínimo de .env (sin dependencias)."""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _env_combinado() -> dict:
    env = dict(os.environ)
    for candidato in (r"C:\Users\lquinones\.env", str(Path.home() / ".env")):
        for k, v in _read_dotenv(candidato).items():
            env.setdefault(k, v)
    return env


def _resolver_credenciales():
    """Devuelve (Credentials, spreadsheet_id) para la cuenta de servicio."""
    # 1) Streamlit secrets
    try:
        import streamlit as st  # import perezoso: los scripts CLI no dependen de streamlit
        if "gcp_service_account" in st.secrets:
            info = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            sid = st.secrets.get("sheets_id") or st.secrets.get("CASOS_SHEETS_ID")
            if not sid:
                raise RuntimeError("Falta 'sheets_id' en los secrets de Streamlit.")
            return creds, sid
    except RuntimeError:
        raise
    except Exception:
        pass  # no hay runtime de streamlit o no hay secret: probamos env

    # 2) Entorno / .env
    env = _env_combinado()
    sa_path = env.get("GOOGLE_SA_PATH")
    if not sa_path or not Path(sa_path).exists():
        raise RuntimeError(
            f"GOOGLE_SA_PATH no apunta a un archivo válido: {sa_path!r}. "
            "Configurar en .env o usar st.secrets."
        )
    sid = env.get("CASOS_SHEETS_ID")
    if not sid:
        raise RuntimeError("Falta CASOS_SHEETS_ID (id del Google Sheet) en .env.")
    creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    return creds, sid


def _get_service():
    global _service, _sheet_id_cached
    if _service is not None:
        return _service
    with _service_lock:
        if _service is not None:
            return _service
        creds, sid = _resolver_credenciales()
        _sheet_id_cached = sid
        _service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        return _service


def _sid() -> str:
    if _sheet_id_cached is None:
        _get_service()
    return _sheet_id_cached


# ----- Utilidades -------------------------------------------------------------

def generar_id(base: str, prefijo: str = "x") -> str:
    """ID estable a partir de un texto base (SHA1 corto, con prefijo legible)."""
    h = hashlib.sha1(str(base).lower().encode("utf-8")).hexdigest()[:8]
    pref = "".join(c for c in (prefijo or "x")[:6].lower() if c.isalnum()) or "x"
    return f"{pref}-{h}"


def _celda(v):
    return "" if v is None else v


def _rows_to_dicts(values, headers):
    out = []
    for idx, raw in enumerate(values[1:], start=2):  # fila 1 = headers; A2 = primera
        padded = list(raw) + [""] * (len(headers) - len(raw))
        d = dict(zip(headers, padded))
        d["_row"] = idx
        out.append(d)
    return out


# ----- Asegurar estructura ----------------------------------------------------

def asegurar_estructura():
    """Crea las 3 pestañas y sus encabezados si faltan. Idempotente."""
    svc = _get_service()
    sid = _sid()
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    existentes = {s["properties"]["title"] for s in meta.get("sheets", [])}

    requests = []
    for hoja in (HOJA_CASOS, HOJA_AGENDA, HOJA_ADJUNTOS):
        if hoja not in existentes:
            requests.append({"addSheet": {"properties": {"title": hoja}}})
    if requests:
        try:
            svc.spreadsheets().batchUpdate(
                spreadsheetId=sid, body={"requests": requests}).execute()
        except HttpError as e:
            # Tolerar carrera: otra ejecución pudo crear la pestaña en el medio.
            if "already exists" not in str(e):
                raise
        _sheet_gids.clear()

    for hoja, headers in ((HOJA_CASOS, CASOS_HEADERS),
                          (HOJA_AGENDA, AGENDA_HEADERS),
                          (HOJA_ADJUNTOS, ADJUNTOS_HEADERS)):
        got = svc.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{hoja}!1:1").execute()
        if not got.get("values"):
            svc.spreadsheets().values().update(
                spreadsheetId=sid, range=f"{hoja}!A1",
                valueInputOption="RAW", body={"values": [headers]},
            ).execute()


# ----- Cache ------------------------------------------------------------------

_cache = {"casos": {"ts": 0.0, "rows": []},
          "agenda": {"ts": 0.0, "rows": []},
          "adjuntos": {"ts": 0.0, "rows": []}}
_cache_lock = threading.Lock()


def invalidar_cache():
    with _cache_lock:
        for k in _cache:
            _cache[k]["ts"] = 0.0


def _listar(nombre, hoja, rango, headers, force_refresh):
    now = time.time()
    with _cache_lock:
        c = _cache[nombre]
        if not force_refresh and (now - c["ts"] < CACHE_TTL):
            return c["rows"]
        svc = _get_service()
        res = svc.spreadsheets().values().get(
            spreadsheetId=_sid(), range=f"{hoja}!{rango}").execute()
        values = res.get("values", [])
        rows = _rows_to_dicts(values, headers) if values else []
        c.update({"ts": now, "rows": rows})
        return rows


# ----- Casos ------------------------------------------------------------------

def listar_casos(force_refresh: bool = False) -> list[dict]:
    return _listar("casos", HOJA_CASOS, RANGO_CASOS, CASOS_HEADERS, force_refresh)


def ids_existentes() -> set:
    return {r["id"] for r in listar_casos(force_refresh=True) if r.get("id")}


def _buscar_caso(cid: str):
    for r in listar_casos(force_refresh=True):
        if str(r.get("id")) == str(cid):
            return r
    return None


def _nuevo_id_caso(caso: dict) -> str:
    """ID único para un caso. Base = rubro|area|cliente|(expediente o fecha)."""
    distintivo = (caso.get("expediente") or caso.get("fecha_despido")
                  or caso.get("fecha_accidente") or caso.get("fecha_inicio_demanda")
                  or datetime.now().strftime("%Y%m%d%H%M%S"))
    base = f"{caso.get('rubro','')}|{caso.get('area','')}|{caso.get('cliente','')}|{distintivo}"
    pref = (caso.get("cliente") or caso.get("area") or "caso")
    cid = generar_id(base, pref)
    existentes = ids_existentes()
    if cid not in existentes:
        return cid
    i = 2
    while f"{cid}-{i}" in existentes:
        i += 1
    return f"{cid}-{i}"


def append_caso(caso: dict) -> str:
    """Agrega un caso (fila completa A:AG). Devuelve el id."""
    svc = _get_service()
    cid = caso.get("id") or _nuevo_id_caso(caso)
    datos = {
        **caso,
        "id": cid,
        "estado_caso": caso.get("estado_caso") or "Abierto",
        "creado_ts": caso.get("creado_ts") or datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    row = [_celda(datos.get(h, "")) for h in CASOS_HEADERS]
    svc.spreadsheets().values().append(
        spreadsheetId=_sid(), range=f"{HOJA_CASOS}!{RANGO_CASOS}",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    invalidar_cache()
    return cid


def actualizar_caso(cid: str, cambios: dict) -> bool:
    """Reescribe la fila completa de un caso aplicando `cambios`.

    Sólo pisa las columnas presentes en `cambios`; el resto (id, creado_ts,
    y cualquier campo de otra área) se preserva. Edición en el lugar.
    """
    r = _buscar_caso(cid)
    if not r:
        return False
    svc = _get_service()
    fila = r["_row"]
    row = [_celda(cambios[h] if h in cambios else r.get(h, "")) for h in CASOS_HEADERS]
    ultima_col = _col_letter(len(CASOS_HEADERS))
    svc.spreadsheets().values().update(
        spreadsheetId=_sid(), range=f"{HOJA_CASOS}!A{fila}:{ultima_col}{fila}",
        valueInputOption="USER_ENTERED", body={"values": [row]},
    ).execute()
    invalidar_cache()
    return True


# ----- Agenda (eventos) -------------------------------------------------------

def listar_agenda(force_refresh: bool = False) -> list[dict]:
    return _listar("agenda", HOJA_AGENDA, RANGO_AGENDA, AGENDA_HEADERS, force_refresh)


def eventos_de_caso(caso_id: str, force_refresh: bool = False) -> list[dict]:
    return [e for e in listar_agenda(force_refresh) if str(e.get("caso_id")) == str(caso_id)]


def append_evento(evento: dict) -> str:
    """Agrega un evento a la Agenda. Devuelve el id del evento."""
    svc = _get_service()
    base = (f"{evento.get('caso_id','')}|{evento.get('tipo','')}|"
            f"{evento.get('fecha','')}|{evento.get('descripcion','')}")
    eid = evento.get("id") or generar_id(base, "ev")
    datos = {
        **evento,
        "id": eid,
        "estado": evento.get("estado") or ESTADO_EVENTO_PENDIENTE,
        "recordar_dias": evento.get("recordar_dias", 7),
        "creado_ts": evento.get("creado_ts") or datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "gcal_event_id": evento.get("gcal_event_id", ""),
    }
    row = [_celda(datos.get(h, "")) for h in AGENDA_HEADERS]
    svc.spreadsheets().values().append(
        spreadsheetId=_sid(), range=f"{HOJA_AGENDA}!{RANGO_AGENDA}",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    invalidar_cache()
    return eid


def _buscar_evento(eid: str):
    for e in listar_agenda(force_refresh=True):
        if str(e.get("id")) == str(eid):
            return e
    return None


def actualizar_evento(eid: str, cambios: dict) -> bool:
    """Reescribe la fila completa de un evento aplicando `cambios`."""
    e = _buscar_evento(eid)
    if not e:
        return False
    svc = _get_service()
    fila = e["_row"]
    row = [_celda(cambios[h] if h in cambios else e.get(h, "")) for h in AGENDA_HEADERS]
    ultima_col = _col_letter(len(AGENDA_HEADERS))
    svc.spreadsheets().values().update(
        spreadsheetId=_sid(), range=f"{HOJA_AGENDA}!A{fila}:{ultima_col}{fila}",
        valueInputOption="USER_ENTERED", body={"values": [row]},
    ).execute()
    invalidar_cache()
    return True


def set_gcal_event_id(eid: str, gcal_event_id: str) -> bool:
    """Guarda el id del evento espejo de Google Calendar (columna I)."""
    return actualizar_evento(eid, {"gcal_event_id": gcal_event_id or ""})


def marcar_evento_cumplido(eid: str, cumplido: bool = True) -> bool:
    estado = ESTADO_EVENTO_CUMPLIDO if cumplido else ESTADO_EVENTO_PENDIENTE
    return actualizar_evento(eid, {"estado": estado})


def borrar_evento(eid: str) -> bool:
    e = _buscar_evento(eid)
    if not e:
        return False
    _borrar_fila(HOJA_AGENDA, e["_row"])
    return True


# ----- Adjuntos ---------------------------------------------------------------

def listar_adjuntos(force_refresh: bool = False) -> list[dict]:
    return _listar("adjuntos", HOJA_ADJUNTOS, RANGO_ADJUNTOS, ADJUNTOS_HEADERS, force_refresh)


def adjuntos_de_caso(caso_id: str, force_refresh: bool = False) -> list[dict]:
    return [a for a in listar_adjuntos(force_refresh) if str(a.get("caso_id")) == str(caso_id)]


def append_adjunto(adjunto: dict) -> str:
    """Agrega un adjunto (link de Drive ya subido). Devuelve el id."""
    svc = _get_service()
    base = (f"{adjunto.get('caso_id','')}|{adjunto.get('tipo','')}|"
            f"{adjunto.get('url','')}|{adjunto.get('fecha','')}")
    aid = adjunto.get("id") or generar_id(base, "adj")
    datos = {
        **adjunto,
        "id": aid,
        "creado_ts": adjunto.get("creado_ts") or datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    row = [_celda(datos.get(h, "")) for h in ADJUNTOS_HEADERS]
    svc.spreadsheets().values().append(
        spreadsheetId=_sid(), range=f"{HOJA_ADJUNTOS}!{RANGO_ADJUNTOS}",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    invalidar_cache()
    return aid


def _buscar_adjunto(aid: str):
    for a in listar_adjuntos(force_refresh=True):
        if str(a.get("id")) == str(aid):
            return a
    return None


def borrar_adjunto(aid: str) -> bool:
    a = _buscar_adjunto(aid)
    if not a:
        return False
    _borrar_fila(HOJA_ADJUNTOS, a["_row"])
    return True


# ----- Borrar caso (cascada) --------------------------------------------------

def borrar_caso(cid: str) -> list[str]:
    """Elimina un caso y EN CASCADA sus eventos y adjuntos.

    Devuelve la lista de gcal_event_id de los eventos que tenían espejo en
    Google Calendar, para que la capa de UI los borre del calendario.
    """
    eventos = eventos_de_caso(cid, force_refresh=True)
    adjuntos = adjuntos_de_caso(cid, force_refresh=True)
    gcal_ids = [e.get("gcal_event_id") for e in eventos if e.get("gcal_event_id")]

    # Borrar de abajo hacia arriba en cada pestaña (no corre los _row restantes).
    for row in sorted((e["_row"] for e in eventos), reverse=True):
        _borrar_fila(HOJA_AGENDA, row)
    for row in sorted((a["_row"] for a in adjuntos), reverse=True):
        _borrar_fila(HOJA_ADJUNTOS, row)

    r = _buscar_caso(cid)
    if r:
        _borrar_fila(HOJA_CASOS, r["_row"])
    invalidar_cache()
    return gcal_ids


# ----- Borrado físico de filas ------------------------------------------------

_sheet_gids: dict = {}


def _col_letter(col_num: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA, 33 -> AG."""
    letters = ""
    while col_num > 0:
        col_num, rem = divmod(col_num - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _sheet_id_por_titulo(titulo: str) -> int:
    """gid numérico de una pestaña (lo pide la API para borrar filas). Cacheado."""
    if titulo in _sheet_gids:
        return _sheet_gids[titulo]
    svc = _get_service()
    meta = svc.spreadsheets().get(spreadsheetId=_sid()).execute()
    for s in meta.get("sheets", []):
        props = s["properties"]
        _sheet_gids[props["title"]] = props["sheetId"]
    if titulo not in _sheet_gids:
        raise RuntimeError(f"No existe la pestaña {titulo!r}")
    return _sheet_gids[titulo]


def _borrar_fila(hoja_titulo: str, row_number: int) -> None:
    """Elimina físicamente la fila row_number (1-indexada) de la pestaña."""
    svc = _get_service()
    gid = _sheet_id_por_titulo(hoja_titulo)
    svc.spreadsheets().batchUpdate(
        spreadsheetId=_sid(),
        body={"requests": [{"deleteDimension": {"range": {
            "sheetId": gid, "dimension": "ROWS",
            "startIndex": row_number - 1, "endIndex": row_number,
        }}}]},
    ).execute()
    invalidar_cache()
