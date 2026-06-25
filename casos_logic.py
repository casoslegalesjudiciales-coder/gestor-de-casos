"""casos_logic.py — Lógica pura del Gestor de Casos (sin I/O, sin red).

Define:
  • Constantes de clasificación: RUBROS, AREAS, estados de caso.
  • SCHEMA: qué campos escalares muestra cada (rubro, área) en el formulario.
    Es el corazón "schema-driven": agregar/editar un área = editar este dict.
  • Parsers/formatters de fecha (dd/mm/aaaa) y monto argentino.
  • Semáforo de vencimientos sobre los eventos de la Agenda.

Solo stdlib. Recibe dicts (filas del Google Sheet) y devuelve datos derivados.
Pensado para poder probarse local sin tocar Google (ver pruebas al pie del repo).
"""

from __future__ import annotations

from datetime import date, datetime


# ============================================================================
# Clasificación: rubros y áreas
# ============================================================================

RUBROS = ["Extrajudicial", "Judicial"]
AREAS = ["Despido", "ART", "Accidente de Tránsito", "Otros"]

ESTADOS_CASO = ["Abierto", "En trámite", "Cerrado"]

# Opciones sugeridas para los desplegables de las sub-entidades (la UI permite
# además escribir un tipo libre).
TIPOS_EVENTO = [
    "Audiencia SECLO", "Audiencia testimonial", "Audiencia", "Pericia médica",
    "Examen médico", "Vencimiento de plazo", "Traslado de demanda",
    "Traba de litis", "Sentencia", "Recordatorio telegrama", "Otro",
]
TIPOS_ADJUNTO = [
    "Telegrama", "Alta/Rechazo ART", "Dictamen médico", "Foto daños",
    "Foto lesiones", "Expediente", "Sentencia", "Otro",
]


# ============================================================================
# SCHEMA del formulario por (rubro, área)
# ============================================================================
# Cada campo: clave (= header en la pestaña Casos), etiqueta (lo que ve el
# usuario), tipo ∈ {texto, area_text, fecha, monto, si_no, select}, y opcional:
#   obligatorio: bool
#   opciones: [..]        (para tipo 'select')
#   depende_de: (clave, valor)  -> solo se muestra si ese otro campo == valor
# Las sub-entidades repetibles (telegramas, audiencias, fotos, archivos de
# dictamen/alta/sentencia) NO van acá: se cargan en bloques fijos del form
# "Ver / editar caso" que escriben a las pestañas Agenda y Adjuntos.

CAMPOS_COMUNES = [
    {"clave": "cliente", "etiqueta": "Cliente", "tipo": "texto", "obligatorio": True},
    {"clave": "estado_caso", "etiqueta": "Estado del caso", "tipo": "select",
     "opciones": ESTADOS_CASO},
]

# Campos del acuerdo, reutilizados en varias áreas (siempre condicionados a
# hubo_acuerdo == "Sí").
_CAMPOS_ACUERDO = [
    {"clave": "monto_acuerdo", "etiqueta": "Monto del acuerdo", "tipo": "monto",
     "depende_de": ("hubo_acuerdo", "Sí")},
    {"clave": "forma_pago", "etiqueta": "Forma de pago", "tipo": "texto",
     "depende_de": ("hubo_acuerdo", "Sí")},
    {"clave": "fecha_acuerdo", "etiqueta": "Fecha del acuerdo", "tipo": "fecha",
     "depende_de": ("hubo_acuerdo", "Sí")},
]

# Campos compartidos por las tres áreas judiciales que comparten flujo (ART y
# Accidente de Tránsito son idénticos según el pedido del cliente).
_JUDICIAL_ART_TRANSITO = [
    {"clave": "expediente", "etiqueta": "Expediente", "tipo": "texto"},
    {"clave": "juzgado", "etiqueta": "Número de juzgado", "tipo": "texto"},
    {"clave": "fecha_inicio_demanda", "etiqueta": "Inicio de demanda", "tipo": "fecha"},
    {"clave": "fecha_contestacion_demanda", "etiqueta": "Contestación de demanda", "tipo": "fecha"},
    {"clave": "fecha_pericia", "etiqueta": "Audiencia", "tipo": "fecha"},
    {"clave": "fecha_examen_medico", "etiqueta": "Examen médico", "tipo": "fecha"},
    {"clave": "fecha_audiencia_testimonial", "etiqueta": "Audiencia testimonial", "tipo": "fecha"},
    {"clave": "fecha_sentencia", "etiqueta": "Fecha de sentencia", "tipo": "fecha"},
    {"clave": "sentencia_texto", "etiqueta": "Sentencia (texto / resumen)", "tipo": "area_text"},
]

SCHEMA = {
    # ---------------- EXTRAJUDICIALES ----------------
    ("Extrajudicial", "Despido"): [
        {"clave": "empresa", "etiqueta": "Empresa (empleadora)", "tipo": "texto"},
        {"clave": "fecha_despido", "etiqueta": "Fecha de despido", "tipo": "fecha"},
        # Telegramas -> Adjuntos (tipo=Telegrama, con fecha de envío).
        # Audiencia SECLO + recordatorios -> Agenda.
        {"clave": "hubo_acuerdo", "etiqueta": "¿Se acordó en la audiencia?", "tipo": "si_no"},
        *_CAMPOS_ACUERDO,
    ],
    ("Extrajudicial", "ART"): [
        {"clave": "seguro", "etiqueta": "Nombre del seguro (ART)", "tipo": "texto"},
        {"clave": "diagnostico", "etiqueta": "Diagnóstico", "tipo": "area_text"},
        {"clave": "fecha_alta_o_rechazo", "etiqueta": "Fecha de alta médica / rechazo de ART",
         "tipo": "fecha"},
        # El archivo del alta/rechazo y el del dictamen -> Adjuntos.
        {"clave": "fecha_inicio_comisiones", "etiqueta": "Inicio en comisiones médicas",
         "tipo": "fecha"},
        {"clave": "fecha_pericia", "etiqueta": "Fecha de audiencia médica", "tipo": "fecha"},
        {"clave": "dictamen_texto", "etiqueta": "Dictamen médico (resumen)", "tipo": "area_text"},
        {"clave": "hubo_acuerdo", "etiqueta": "¿Hubo acuerdo?", "tipo": "si_no"},
    ],
    ("Extrajudicial", "Accidente de Tránsito"): [
        {"clave": "seguro", "etiqueta": "Nombre del seguro", "tipo": "texto"},
        {"clave": "fecha_accidente", "etiqueta": "Fecha del accidente", "tipo": "fecha"},
        {"clave": "danos_materiales", "etiqueta": "¿Hay daños materiales?", "tipo": "si_no"},
        # Fotos de daños -> Adjuntos (tipo=Foto daños).
        {"clave": "hay_lesiones", "etiqueta": "¿Hay lesiones?", "tipo": "si_no"},
        {"clave": "diagnostico", "etiqueta": "Diagnóstico de las lesiones", "tipo": "area_text",
         "depende_de": ("hay_lesiones", "Sí")},
        # Fotos de lesiones -> Adjuntos (tipo=Foto lesiones).
        {"clave": "fecha_pericia", "etiqueta": "Fecha de pericia médica", "tipo": "fecha"},
        {"clave": "hubo_acuerdo", "etiqueta": "¿Hubo acuerdo?", "tipo": "si_no"},
        {"clave": "monto_acuerdo", "etiqueta": "Monto del acuerdo", "tipo": "monto",
         "depende_de": ("hubo_acuerdo", "Sí")},
        {"clave": "fecha_acuerdo", "etiqueta": "Fecha del acuerdo", "tipo": "fecha",
         "depende_de": ("hubo_acuerdo", "Sí")},
    ],

    # ---------------- JUDICIALES ----------------
    ("Judicial", "Despido"): [
        {"clave": "expediente", "etiqueta": "Expediente", "tipo": "texto"},
        {"clave": "juzgado", "etiqueta": "Número de juzgado", "tipo": "texto"},
        {"clave": "fecha_inicio_demanda", "etiqueta": "Inicio de demanda", "tipo": "fecha"},
        {"clave": "fecha_traslado_demanda", "etiqueta": "Traslado de demanda", "tipo": "fecha"},
        {"clave": "fecha_traba_litis", "etiqueta": "Traba de litis", "tipo": "fecha"},
        {"clave": "fecha_audiencia_art80", "etiqueta": "Audiencia art. 80", "tipo": "fecha"},
        {"clave": "fecha_audiencia_testimonial", "etiqueta": "Audiencia testimoniales",
         "tipo": "fecha"},
        {"clave": "fecha_sentencia", "etiqueta": "Fecha de sentencia", "tipo": "fecha"},
        {"clave": "sentencia_texto", "etiqueta": "Sentencia (texto / resumen)", "tipo": "area_text"},
        # Agendamientos diversos -> Agenda (N eventos).
    ],
    ("Judicial", "ART"): _JUDICIAL_ART_TRANSITO,
    ("Judicial", "Accidente de Tránsito"): _JUDICIAL_ART_TRANSITO,
}

# Campo genérico para las áreas "Otros" (el cliente no especificó campos).
_CAMPO_GENERICO = [
    {"clave": "descripcion", "etiqueta": "Descripción del reclamo", "tipo": "area_text"},
]


def campos_de(rubro: str, area: str) -> list[dict]:
    """Lista de campos a renderizar para un (rubro, área): comunes + específicos.

    Si la combinación no está en SCHEMA (caso "Otros"), cae al campo genérico.
    """
    especificos = SCHEMA.get((rubro, area), _CAMPO_GENERICO)
    return CAMPOS_COMUNES + especificos


def claves_de_caso(rubro: str, area: str) -> list[str]:
    """Claves (columnas) que usa un (rubro, área). Útil para limpiar/validar."""
    return [c["clave"] for c in campos_de(rubro, area)]


# ============================================================================
# Fechas
# ============================================================================

def parse_fecha(s):
    """'dd/mm/aaaa' (o 'yyyy-mm-dd') -> date, o None."""
    if not s:
        return None
    if isinstance(s, date):
        return s
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fmt_fecha(d):
    """date -> 'dd/mm/aaaa', o '' si None."""
    return d.strftime("%d/%m/%Y") if d else ""


def add_months(d, n):
    """Suma n meses a una fecha, recortando el día al último día válido."""
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year, month + 1, 1) - date(year, month, 1)).days
    return date(year, month, min(d.day, last_day))


# ============================================================================
# Montos argentinos ('.' miles, ',' decimales)
# ============================================================================

def parse_monto_ar(s):
    """'27.000,00' -> 27000.0 ; '27000' -> 27000.0 ; vacío/inválido -> None."""
    if s is None:
        return None
    s = str(s).strip().replace(" ", "").replace("$", "")
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def formatear_monto_ar(s):
    """'56000' -> '56.000' ; '56000,5' -> '56.000,50'. None si no parsea."""
    v = parse_monto_ar(s)
    if v is None:
        return None
    if v == int(v):
        return f"{int(v):,}".replace(",", ".")
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_money(v):
    """Float/str -> '$ 27.000,00'. '' si vacío."""
    if v in (None, ""):
        return ""
    try:
        return f"$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return str(v)


# ============================================================================
# Semáforo y agenda
# ============================================================================
# Estados de un evento respecto de hoy:
#   vencido  🔴  (fecha pasada, pendiente)
#   hoy      🟠  (es hoy)
#   proximo  🟡  (dentro de los próximos `recordar_dias`)
#   futuro   🟢  (más lejos)
#   sin_dato ⚪  (sin fecha)

EMOJI_ESTADO = {
    "vencido": "🔴",
    "hoy": "🟠",
    "proximo": "🟡",
    "futuro": "🟢",
    "sin_dato": "⚪",
}

# Prioridad para elegir el "peor" estado de un caso (menor = más urgente).
_ORDEN_ESTADO = {"vencido": 0, "hoy": 1, "proximo": 2, "futuro": 3, "sin_dato": 4}

RECORDAR_DIAS_DEFAULT = 7
ESTADO_EVENTO_PENDIENTE = "Pendiente"
ESTADO_EVENTO_CUMPLIDO = "Cumplido"


def _recordar_dias(valor) -> int:
    try:
        n = int(str(valor).strip())
        return n if n >= 0 else RECORDAR_DIAS_DEFAULT
    except (ValueError, TypeError):
        return RECORDAR_DIAS_DEFAULT


def estado_evento(fecha, hoy, recordar_dias=RECORDAR_DIAS_DEFAULT):
    """Devuelve (codigo, etiqueta) de un evento de Agenda respecto de `hoy`.

    codigo ∈ {'vencido', 'hoy', 'proximo', 'futuro', 'sin_dato'}.
    """
    if fecha is None:
        return ("sin_dato", "Sin fecha")
    delta = (fecha - hoy).days
    if delta < 0:
        return ("vencido", f"Venció hace {abs(delta)} día(s)")
    if delta == 0:
        return ("hoy", "¡Es HOY!")
    if delta <= recordar_dias:
        return ("proximo", f"En {delta} día(s)")
    return ("futuro", f"El {fmt_fecha(fecha)}")


def proximos_eventos(eventos, hoy, incluir_cumplidos=False):
    """Enriquece y ORDENA por fecha asc. una lista de eventos (dicts de Agenda).

    Filtra los 'Cumplido' salvo que se pida lo contrario. Agrega a cada evento:
    fecha_d (date|None), codigo, etiqueta, emoji.
    """
    out = []
    for e in eventos:
        if not incluir_cumplidos and e.get("estado") == ESTADO_EVENTO_CUMPLIDO:
            continue
        fd = parse_fecha(e.get("fecha"))
        rd = _recordar_dias(e.get("recordar_dias"))
        cod, et = estado_evento(fd, hoy, rd)
        out.append({**e, "fecha_d": fd, "codigo": cod, "etiqueta": et,
                    "emoji": EMOJI_ESTADO[cod]})
    out.sort(key=lambda x: x["fecha_d"] or date.max)
    return out


def estado_caso_semaforo(eventos_del_caso, hoy):
    """Peor estado (más urgente) entre los eventos PENDIENTES de un caso.

    Devuelve un código de EMOJI_ESTADO; 'sin_dato' si no hay eventos pendientes.
    """
    codigos = [
        estado_evento(parse_fecha(e.get("fecha")), hoy,
                      _recordar_dias(e.get("recordar_dias")))[0]
        for e in eventos_del_caso
        if e.get("estado") != ESTADO_EVENTO_CUMPLIDO
    ]
    if not codigos:
        return "sin_dato"
    return min(codigos, key=lambda c: _ORDEN_ESTADO[c])
