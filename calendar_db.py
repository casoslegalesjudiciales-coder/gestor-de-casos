"""calendar_db.py — Recordatorios: Google Calendar (push) + .ics (respaldo).

Dos caminos:
  • construir_ics(eventos)  — SIEMPRE disponible (stdlib, sin red). Genera un
    archivo .ics que el estudio importa una vez al calendario del celular; cada
    evento lleva una alarma N días antes.
  • upsert/borrar en Google Calendar — vía OAuth (oauth_creds). Crea/edita/borra
    eventos all-day reales en el calendario del estudio, con notificación push.
    Requiere oauth + calendar_id; si falta, calendar_disponible()=False y la app
    sigue andando con el .ics.

`evento` es un dict de la pestaña Agenda (casos_db.AGENDA_HEADERS), opcionalmente
enriquecido con 'cliente' para un título más claro.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import casos_db
import casos_logic as cl
import oauth_creds


# ----- Config -----------------------------------------------------------------

def _calendar_id() -> str:
    try:
        import streamlit as st
        cid = st.secrets.get("calendar_id")
        if cid:
            return str(cid)
    except Exception:
        pass
    return casos_db._env_combinado().get("CALENDAR_ID", "")


def calendar_disponible() -> bool:
    """True si se puede crear eventos en Google Calendar (oauth + calendar_id)."""
    return bool(oauth_creds.disponible() and _calendar_id())


# ----- Helpers ----------------------------------------------------------------

def _titulo(evento: dict) -> str:
    tipo = (evento.get("tipo") or "Evento").strip()
    cliente = (evento.get("cliente") or "").strip()
    desc = (evento.get("descripcion") or "").strip()
    partes = [tipo]
    if cliente:
        partes.append(cliente)
    titulo = " — ".join(partes)
    if desc and desc.lower() not in titulo.lower():
        titulo += f": {desc}"
    return titulo[:300]


def _minutos_antes(evento: dict) -> int:
    try:
        n = int(str(evento.get("recordar_dias") or cl.RECORDAR_DIAS_DEFAULT))
    except (ValueError, TypeError):
        n = cl.RECORDAR_DIAS_DEFAULT
    return max(0, n) * 24 * 60


# ----- Google Calendar (OAuth) ------------------------------------------------

def upsert_evento_calendar(evento: dict) -> str:
    """Crea o actualiza un evento all-day en el calendario del estudio.

    Si evento['gcal_event_id'] ya existe, lo ACTUALIZA; si no, lo CREA.
    Devuelve el id del evento de Calendar (o '' si no se pudo / no configurado).
    """
    if not calendar_disponible():
        return ""
    fecha = cl.parse_fecha(evento.get("fecha"))
    if fecha is None:
        return ""  # sin fecha no hay evento de calendario

    svc = oauth_creds.get_calendar_service()
    cal_id = _calendar_id()
    minutos = _minutos_antes(evento)
    body = {
        "summary": _titulo(evento),
        "description": (f"Caso: {evento.get('caso_id','')}\n"
                        f"{evento.get('descripcion','')}").strip(),
        "start": {"date": fecha.strftime("%Y-%m-%d")},
        "end": {"date": (fecha + timedelta(days=1)).strftime("%Y-%m-%d")},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": minutos},
                {"method": "email", "minutes": minutos},
            ],
        },
    }
    gid = (evento.get("gcal_event_id") or "").strip()
    if gid:
        try:
            res = svc.events().update(
                calendarId=cal_id, eventId=gid, body=body).execute()
            return res.get("id", gid)
        except Exception:
            pass  # el evento pudo haberse borrado a mano: lo recreamos
    res = svc.events().insert(calendarId=cal_id, body=body).execute()
    return res.get("id", "")


def borrar_evento_calendar(gcal_event_id: str) -> bool:
    """Borra un evento del calendario del estudio. Tolera que ya no exista."""
    gid = (gcal_event_id or "").strip()
    if not gid or not calendar_disponible():
        return False
    try:
        oauth_creds.get_calendar_service().events().delete(
            calendarId=_calendar_id(), eventId=gid).execute()
        return True
    except Exception:
        return False


# ----- .ics (respaldo, siempre disponible) ------------------------------------

def _escape_ics(texto: str) -> str:
    s = str(texto or "")
    return (s.replace("\\", "\\\\").replace(";", "\\;")
             .replace(",", "\\,").replace("\n", "\\n"))


def construir_ics(eventos, nombre_cal: str = "Agenda Estudio") -> str:
    """Texto .ics (VCALENDAR) con un VEVENT all-day por evento (con su alarma).

    `eventos` = filas de Agenda (dicts). Ignora los sin fecha. Cada VALARM se
    dispara `recordar_dias` antes. Importable a cualquier calendario.
    """
    dtstamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    lineas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Gestor de Casos//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_ics(nombre_cal)}",
    ]
    for e in eventos:
        fecha = cl.parse_fecha(e.get("fecha"))
        if fecha is None:
            continue
        uid = f"{e.get('id') or _escape_ics(e.get('descripcion',''))}@gestor-casos"
        ini = fecha.strftime("%Y%m%d")
        fin = (fecha + timedelta(days=1)).strftime("%Y%m%d")
        try:
            ndias = max(0, int(str(e.get("recordar_dias") or cl.RECORDAR_DIAS_DEFAULT)))
        except (ValueError, TypeError):
            ndias = cl.RECORDAR_DIAS_DEFAULT
        titulo = _titulo(e)
        lineas += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART;VALUE=DATE:{ini}",
            f"DTEND;VALUE=DATE:{fin}",
            f"SUMMARY:{_escape_ics(titulo)}",
            f"DESCRIPTION:{_escape_ics(e.get('descripcion',''))}",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape_ics(titulo)}",
            f"TRIGGER:-P{ndias}D",
            "END:VALARM",
            "END:VEVENT",
        ]
    lineas.append("END:VCALENDAR")
    return "\r\n".join(lineas) + "\r\n"
