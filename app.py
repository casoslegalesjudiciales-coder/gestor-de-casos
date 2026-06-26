"""app.py — Gestor de Casos (estudio jurídico). App web multiusuario.

Streamlit + Google Sheets (datos) + Drive (adjuntos, OAuth) + Google Calendar /
.ics (recordatorios). Base COMPARTIDA: lo que carga una persona lo ven todas.

Objetivo: que el estudio NO pierda audiencias ni plazos procesales.

Secciones:
  📋 Casos            — listado con semáforo + filtros
  ➕ Nuevo caso       — alta (formulario que se adapta al rubro/área)
  🔎 Ver / editar     — editar caso + telegramas, agenda y adjuntos
  📅 Agenda           — próximos vencimientos globales + descargar .ics
  ⬇️ Exportar         — CSV de Casos / Agenda / Adjuntos
  🗑️ Borrar           — caso (cascada) o evento/adjunto suelto

Correr local:  streamlit run app.py
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import casos_db as db
import casos_logic as cl
import drive_casos as drive
import calendar_db as cal
import docx_export as dx

st.set_page_config(page_title="Gestor de Casos", page_icon="⚖️", layout="wide")


# ----- Acceso (clave única compartida) ---------------------------------------

def _clave_app() -> str:
    import os
    try:
        clave = st.secrets.get("app_password")
    except Exception:
        clave = None
    return str(clave or os.getenv("CASOS_APP_PASSWORD", "estudio-2026"))


def _check_password() -> bool:
    if st.session_state.get("auth_ok"):
        return True
    st.title("🔒 Gestor de Casos")
    st.caption("Ingresá la clave de acceso del estudio.")
    pwd = st.text_input("Contraseña", type="password", key="login_pwd")
    if st.button("Entrar", type="primary"):
        if pwd == _clave_app():
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    return False


if not _check_password():
    st.stop()


# ----- Helpers de datos -------------------------------------------------------

def _refrescar(*cuales):
    """Invalida el cache. Sin argumentos: todo. Con argumentos (subconjunto de
    'casos'/'agenda'/'adjuntos'): recarga SOLO esas tablas de Google y mantiene
    las demás en cache → cada acción hace 1 sola lectura en vez de 3."""
    db.invalidar_cache()
    if not cuales:
        st.cache_data.clear()
        return
    mapa = {"casos": cargar_casos, "agenda": cargar_agenda, "adjuntos": cargar_adjuntos}
    for c in cuales:
        if c in mapa:
            mapa[c].clear()


def _limpiar_keys(prefijo: str):
    """Borra del session_state los widgets cuyo key empieza con `prefijo`
    (para resetear un formulario tras guardarlo). Seguro de llamar antes de rerun."""
    for k in [k for k in list(st.session_state.keys()) if k.startswith(prefijo)]:
        st.session_state.pop(k, None)


@st.cache_data(ttl=db.CACHE_TTL, show_spinner=False)
def cargar_casos():
    return db.listar_casos(force_refresh=True)


@st.cache_data(ttl=db.CACHE_TTL, show_spinner=False)
def cargar_agenda():
    return db.listar_agenda(force_refresh=True)


@st.cache_data(ttl=db.CACHE_TTL, show_spinner=False)
def cargar_adjuntos():
    return db.listar_adjuntos(force_refresh=True)


def _monto_prefill(v):
    if v in (None, ""):
        return ""
    f = cl.formatear_monto_ar(str(v))
    return f if f is not None else str(v)


def _agrupar_por_caso(filas):
    out = {}
    for r in filas:
        out.setdefault(str(r.get("caso_id")), []).append(r)
    return out


def _label_caso(c: dict) -> str:
    extra = c.get("expediente") or c.get("empresa") or c.get("seguro") or ""
    extra = f" · {extra}" if extra else ""
    return (f"{c.get('cliente','(sin cliente)')} — {c.get('rubro','')} · "
            f"{c.get('area','')}{extra}  [{c['id']}]")


def _safe_name(s: str) -> str:
    """Nombre de archivo seguro (para los .docx que se descargan)."""
    s = (s or "caso").strip()
    keep = "".join(c if (c.isalnum() or c in " -_") else "_" for c in s)
    return keep.strip() or "caso"


# ----- Render del formulario schema-driven ------------------------------------

def render_campos(campos, valores, kp) -> dict:
    """Renderiza los `campos` (de casos_logic.campos_de) y devuelve {clave: valor}.

    Respeta `depende_de`: un campo dependiente sólo se muestra (y guarda) si su
    campo padre tiene el valor esperado; si no, se guarda vacío.
    """
    out = {}
    for c in campos:
        clave, tipo = c["clave"], c["tipo"]
        dep = c.get("depende_de")
        if dep:
            padre, esperado = dep
            actual = out.get(padre, valores.get(padre, ""))
            if str(actual) != str(esperado):
                out[clave] = ""  # oculto → se guarda vacío (coherente con la respuesta)
                continue
        key = f"{kp}_{clave}"
        label = c["etiqueta"] + (" *" if c.get("obligatorio") else "")

        if tipo == "texto":
            out[clave] = st.text_input(label, value=valores.get(clave, ""), key=key).strip()
        elif tipo == "area_text":
            out[clave] = st.text_area(label, value=valores.get(clave, ""), key=key).strip()
        elif tipo == "fecha":
            d = st.date_input(label, value=cl.parse_fecha(valores.get(clave)),
                              format="DD/MM/YYYY", key=key)
            out[clave] = cl.fmt_fecha(d) if d else ""
        elif tipo == "monto":
            raw = st.text_input(label, value=_monto_prefill(valores.get(clave)),
                                placeholder="1.500.000,00", key=key,
                                help="Formato argentino: '.' miles, ',' decimales.")
            v = cl.parse_monto_ar(raw)
            out[clave] = v if v is not None else ""
        elif tipo == "si_no":
            opts = ["—", "Sí", "No"]
            actual = valores.get(clave, "")
            idx = opts.index(actual) if actual in opts else 0
            sel = st.selectbox(label, opts, index=idx, key=key)
            out[clave] = "" if sel == "—" else sel
        elif tipo == "select":
            opts = c.get("opciones", [])
            actual = valores.get(clave, "")
            idx = opts.index(actual) if actual in opts else 0
            out[clave] = st.selectbox(label, opts, index=idx, key=key)
    return out


def _tipo_con_otro(label, opciones, key, actual=""):
    """Selectbox con opción 'Otro' que habilita un campo de texto libre."""
    base = list(opciones)
    if "Otro" not in base:
        base = base + ["Otro"]
    if actual and actual in base:
        idx = base.index(actual)
    elif actual:
        idx = base.index("Otro")
    else:
        idx = 0
    sel = st.selectbox(label, base, index=idx, key=key)
    if sel == "Otro":
        libre = st.text_input("Especificá", value=(actual if actual not in opciones else ""),
                              key=f"{key}_otro")
        return libre.strip()
    return sel


# ----- Calendar helpers (alta/baja sincronizada) ------------------------------

def _alta_evento(caso: dict, tipo, descripcion, fecha_str, recordar_dias):
    """Crea un evento de Agenda y su espejo en Google Calendar (si está disponible)."""
    eid = db.append_evento({
        "caso_id": caso["id"], "tipo": tipo, "descripcion": descripcion,
        "fecha": fecha_str, "recordar_dias": recordar_dias,
        "estado": db.ESTADO_EVENTO_PENDIENTE,
    })
    if cal.calendar_disponible() and fecha_str:
        try:
            gid = cal.upsert_evento_calendar({
                "caso_id": caso["id"], "cliente": caso.get("cliente", ""),
                "tipo": tipo, "descripcion": descripcion, "fecha": fecha_str,
                "recordar_dias": recordar_dias,
            })
            if gid:
                db.set_gcal_event_id(eid, gid)
        except Exception:
            pass  # el evento queda igual en la Agenda; el .ics lo cubre
    return eid


def _baja_evento(evento: dict):
    if evento.get("gcal_event_id"):
        cal.borrar_evento_calendar(evento["gcal_event_id"])
    db.borrar_evento(evento["id"])


# ----- Sidebar ----------------------------------------------------------------

SECCIONES = ["📋 Casos", "➕ Nuevo caso", "🔎 Ver / editar caso",
             "📅 Agenda", "⬇️ Exportar", "🗑️ Borrar"]

st.sidebar.title("⚖️ Gestor de Casos")
# Cambio de sección programático (desde "Abrir" en el listado): se aplica ANTES
# de instanciar la radio (setear el key después de crearla lanza excepción).
_goto = st.session_state.pop("goto_seccion", None)
if _goto in SECCIONES:
    st.session_state["seccion"] = _goto
seccion = st.sidebar.radio("Sección", SECCIONES, key="seccion")
if st.sidebar.button("🔄 Actualizar datos"):
    _refrescar()
    st.rerun()

# Conexión + estructura
try:
    # asegurar_estructura() hace varias llamadas a Google: corre UNA sola vez por
    # sesión (no en cada clic) para no relentizar ni pisarse al crear pestañas.
    if not st.session_state.get("_estructura_ok"):
        db.asegurar_estructura()
        st.session_state["_estructura_ok"] = True
    casos = cargar_casos()
    agenda = cargar_agenda()
    adjuntos = cargar_adjuntos()
except Exception as e:  # noqa: BLE001
    st.error(
        "No me pude conectar al Google Sheet. Revisá las credenciales "
        "(st.secrets en la nube, o GOOGLE_SA_PATH + CASOS_SHEETS_ID en .env).\n\n"
        f"Detalle: {e}"
    )
    st.stop()

eventos_por_caso = _agrupar_por_caso(agenda)
adjuntos_por_caso = _agrupar_por_caso(adjuntos)
hoy = date.today()

st.sidebar.caption(f"{len(casos)} caso(s) en la base")
if not cal.calendar_disponible():
    st.sidebar.caption("📅 Calendar: usando .ics (Calendar automático no configurado)")

# Aviso flotante (toast) de la acción anterior: se setea antes de st.rerun() y se
# muestra acá tras recargar, así se ve aunque estés scrolleado o cambie de pestaña.
_toast = st.session_state.pop("toast_msg", None)
if _toast:
    st.toast(_toast, icon="✅")


def _ir_a_caso(cid: str):
    st.session_state["caso_sel"] = cid
    st.session_state["goto_seccion"] = "🔎 Ver / editar caso"  # se aplica al recargar


# =============================================================================
# 📋 CASOS (listado)
# =============================================================================
if seccion == "📋 Casos":
    st.header("📋 Casos")

    f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
    f_rubro = f1.selectbox("Rubro", ["Todos"] + cl.RUBROS)
    f_area = f2.selectbox("Área", ["Todas"] + cl.AREAS)
    f_estado = f3.selectbox("Estado", ["Todos"] + cl.ESTADOS_CASO)
    f_texto = f4.text_input("Buscar (cliente, expediente, empresa, seguro)")

    def _coincide(c):
        if f_rubro != "Todos" and c.get("rubro") != f_rubro:
            return False
        if f_area != "Todas" and c.get("area") != f_area:
            return False
        if f_estado != "Todos" and (c.get("estado_caso") or "Abierto") != f_estado:
            return False
        if f_texto:
            q = f_texto.lower()
            campos = [c.get(k, "") for k in ("cliente", "expediente", "empresa", "seguro", "id")]
            if not any(q in str(v).lower() for v in campos):
                return False
        return True

    filtrados = [c for c in casos if _coincide(c)]

    # Métricas por semáforo
    sem = {c["id"]: cl.estado_caso_semaforo(eventos_por_caso.get(c["id"], []), hoy)
           for c in filtrados}
    n_venc = sum(1 for v in sem.values() if v == "vencido")
    n_hoy = sum(1 for v in sem.values() if v == "hoy")
    n_prox = sum(1 for v in sem.values() if v == "proximo")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Casos", len(filtrados))
    m2.metric("🔴 Con plazo vencido", n_venc)
    m3.metric("🟠 Con algo hoy", n_hoy)
    m4.metric("🟡 Próximos (≤7d)", n_prox)

    if not filtrados:
        st.info("No hay casos para ese filtro.")
    else:
        # Ordenar por urgencia del semáforo
        orden = {"vencido": 0, "hoy": 1, "proximo": 2, "futuro": 3, "sin_dato": 4}
        filtrados.sort(key=lambda c: orden.get(sem[c["id"]], 9))

        for c in filtrados[:300]:
            evs = cl.proximos_eventos(eventos_por_caso.get(c["id"], []), hoy)
            prox = evs[0] if evs else None
            emoji = cl.EMOJI_ESTADO.get(sem[c["id"]], "⚪")
            with st.container(border=True):
                cols = st.columns([4, 3, 3, 1.4])
                cols[0].markdown(
                    f"### {emoji} {c.get('cliente','(sin cliente)')}\n"
                    f"{c.get('rubro','')} · **{c.get('area','')}** · "
                    f"_{c.get('estado_caso') or 'Abierto'}_"
                )
                ref = c.get("expediente") or c.get("empresa") or c.get("seguro") or "—"
                cols[1].markdown(f"**Ref.:** {ref}  \nID: `{c['id']}`")
                if prox:
                    cols[2].markdown(
                        f"**Próximo:** {prox['emoji']} {prox.get('tipo','')}  \n"
                        f"{prox.get('fecha','')} — {prox['etiqueta']}")
                else:
                    cols[2].markdown("_Sin eventos en agenda_")
                if cols[3].button("🔎 Abrir", key=f"open_{c['id']}"):
                    _ir_a_caso(c["id"])
                    st.rerun()


# =============================================================================
# ➕ NUEVO CASO
# =============================================================================
elif seccion == "➕ Nuevo caso":
    st.header("➕ Nuevo caso")

    if "nc_ok" in st.session_state:
        st.success(st.session_state.pop("nc_ok"))

    cc = st.columns(2)
    rubro = cc[0].selectbox("Rubro", cl.RUBROS, key="nc_rubro")
    area = cc[1].selectbox("Área", cl.AREAS, key="nc_area")

    st.divider()
    st.caption(f"Campos para **{rubro} · {area}** (los demás se cargan luego como "
               "telegramas, audiencias y adjuntos).")

    campos = cl.campos_de(rubro, area)
    valores = render_campos(campos, {}, kp=f"nc_{rubro}_{area}")

    if st.button("💾 Crear caso", type="primary"):
        if not (valores.get("cliente") or "").strip():
            st.error("El **Cliente** es obligatorio.")
        else:
            caso = {"rubro": rubro, "area": area, **valores}
            with st.spinner("⏳ Creando el caso… (guardando en la planilla)"):
                cid = db.append_caso(caso)
            _refrescar("casos")
            _limpiar_keys(f"nc_{rubro}_{area}_")  # resetear el form para la próxima carga
            st.session_state["caso_sel"] = cid
            st.session_state["toast_msg"] = "Caso creado correctamente"
            st.session_state["nc_ok"] = (
                f"Caso creado ✅ (id {cid}). Abrilo en **🔎 Ver / editar caso** para "
                "cargarle telegramas, audiencias/plazos y archivos.")
            st.rerun()


# =============================================================================
# 🔎 VER / EDITAR CASO
# =============================================================================
elif seccion == "🔎 Ver / editar caso":
    st.header("🔎 Ver / editar caso")

    if "vc_ok" in st.session_state:
        st.success(st.session_state.pop("vc_ok"))

    if not casos:
        st.info("Todavía no hay casos. Cargá uno en **➕ Nuevo caso**.")
        st.stop()

    opciones = {"— Elegí un caso —": None}
    for c in sorted(casos, key=lambda x: x.get("cliente", "").lower()):
        opciones[_label_caso(c)] = c["id"]
    # preseleccionar el caso recién creado / abierto desde el listado
    pre = st.session_state.get("caso_sel")
    labels = list(opciones.keys())
    idx = 0
    if pre:
        for i, (lbl, cid) in enumerate(opciones.items()):
            if cid == pre:
                idx = i
                break
    sel = st.selectbox("Caso", labels, index=idx, key="vc_sel")
    cid = opciones[sel]
    if not cid:
        st.stop()
    st.session_state["caso_sel"] = cid
    caso = next((c for c in casos if c["id"] == cid), None)
    if not caso:
        st.warning("Ese caso ya no existe (se actualizó la base).")
        st.stop()

    st.subheader(f"{caso.get('cliente','')} — {caso.get('rubro','')} · {caso.get('area','')}")
    st.caption(f"id `{caso['id']}`")

    # Legajo: documento Word completo del caso (datos + agenda + adjuntos con links)
    _leg = dx.legajo_caso(caso, eventos_por_caso.get(caso["id"], []),
                          adjuntos_por_caso.get(caso["id"], []), hoy)
    st.download_button(
        "📄 Descargar legajo (Word)", _leg,
        file_name=f"Legajo - {_safe_name(caso.get('cliente',''))}.docx",
        mime=dx.MIME, help="Documento completo del caso para imprimir o pasarle a otro abogado.")

    tab_datos, tab_agenda, tab_adj = st.tabs(
        ["📝 Datos del caso", "📅 Agenda del caso", "📎 Telegramas y adjuntos"])

    # ---- Datos del caso (form schema-driven en modo edición) ----
    with tab_datos:
        campos = cl.campos_de(caso["rubro"], caso["area"])
        valores = render_campos(campos, caso, kp=f"ed_{caso['id']}")
        if st.button("💾 Guardar cambios", type="primary", key=f"save_{caso['id']}"):
            if not (valores.get("cliente") or "").strip():
                st.error("El **Cliente** es obligatorio.")
            else:
                with st.spinner("⏳ Guardando cambios… (actualizando la planilla)"):
                    db.actualizar_caso(caso["id"], valores)
                _refrescar("casos")
                st.session_state["toast_msg"] = "Cambios guardados"
                st.session_state["vc_ok"] = "Cambios guardados ✅"
                st.rerun()

    # ---- Agenda del caso (audiencias / plazos / recordatorios) ----
    with tab_agenda:
        evs = cl.proximos_eventos(eventos_por_caso.get(caso["id"], []), hoy,
                                  incluir_cumplidos=True)
        if not evs:
            st.info("Sin eventos cargados para este caso.")
        for e in evs:
            with st.container(border=True):
                cols = st.columns([5, 2, 2, 2])
                cumplido = e.get("estado") == db.ESTADO_EVENTO_CUMPLIDO
                marca = "✅ " if cumplido else f"{e['emoji']} "
                cols[0].markdown(
                    f"**{marca}{e.get('tipo','')}** — {e.get('descripcion','') or '—'}")
                cols[1].markdown(f"📆 {e.get('fecha','')}")
                cols[2].markdown(("✔️ Cumplido" if cumplido else e["etiqueta"]))
                with cols[3]:
                    if not cumplido and st.button("✔️ Cumplido", key=f"cmp_{e['id']}"):
                        with st.spinner("⏳ Marcando cumplido…"):
                            db.marcar_evento_cumplido(e["id"], True)
                        _refrescar("agenda")
                        st.session_state["toast_msg"] = "Evento marcado como cumplido"
                        st.rerun()
                    if cumplido and st.button("↩️ Reabrir", key=f"reab_{e['id']}"):
                        with st.spinner("⏳ Reabriendo…"):
                            db.marcar_evento_cumplido(e["id"], False)
                        _refrescar("agenda")
                        st.session_state["toast_msg"] = "Evento reabierto"
                        st.rerun()
                    if st.button("🗑️", key=f"delev_{e['id']}"):
                        with st.spinner("⏳ Borrando evento…"):
                            _baja_evento(e)
                        _refrescar("agenda")
                        st.session_state["toast_msg"] = "Evento borrado"
                        st.rerun()

        st.divider()
        st.markdown("**➕ Agregar audiencia / plazo / recordatorio**")
        ec = st.columns([3, 3, 2, 2])
        with ec[0]:
            ev_tipo = _tipo_con_otro("Tipo", cl.TIPOS_EVENTO, key=f"nev_tipo_{caso['id']}")
        ev_desc = ec[1].text_input("Descripción", key=f"nev_desc_{caso['id']}")
        ev_fecha = ec[2].date_input("Fecha", value=None, format="DD/MM/YYYY",
                                    key=f"nev_fecha_{caso['id']}")
        ev_rec = ec[3].number_input("Avisar (días antes)", min_value=0, max_value=120,
                                    value=7, key=f"nev_rec_{caso['id']}")
        if st.button("➕ Agregar a la agenda", type="primary", key=f"addev_{caso['id']}"):
            if ev_fecha is None:
                st.error("Poné una fecha para el evento.")
            else:
                with st.spinner("⏳ Agendando el evento y sincronizando con el calendario…"):
                    _alta_evento(caso, ev_tipo, ev_desc.strip(),
                                 cl.fmt_fecha(ev_fecha), int(ev_rec))
                _refrescar("agenda")
                _limpiar_keys(f"nev_desc_{caso['id']}")
                _limpiar_keys(f"nev_fecha_{caso['id']}")
                via = "Google Calendar" if cal.calendar_disponible() else "la agenda (.ics)"
                st.session_state["toast_msg"] = f"Evento agendado en {via}"
                st.session_state["vc_ok"] = f"Evento agregado a {via} ✅"
                st.rerun()

    # ---- Telegramas y adjuntos ----
    with tab_adj:
        items = adjuntos_por_caso.get(caso["id"], [])
        if not items:
            st.info("Sin archivos cargados para este caso.")
        for a in sorted(items, key=lambda x: x.get("creado_ts", ""), reverse=True):
            with st.container(border=True):
                cols = st.columns([3, 4, 2, 1])
                cols[0].markdown(f"**{a.get('tipo','')}**")
                desc = a.get("descripcion", "") or "—"
                url = a.get("url", "")
                cols[1].markdown(f"{desc}  \n[📄 Abrir archivo]({url})" if url else desc)
                cols[2].markdown(f"📆 {a.get('fecha','') or '—'}")
                if cols[3].button("🗑️", key=f"deladj_{a['id']}"):
                    with st.spinner("⏳ Borrando adjunto…"):
                        db.borrar_adjunto(a["id"])
                    _refrescar("adjuntos")
                    st.session_state["toast_msg"] = "Adjunto borrado"
                    st.rerun()

        st.divider()
        st.markdown("**⬆️ Subir archivo(s)** — telegramas, dictámenes, fotos, expediente, etc.")
        if not drive.disponible():
            st.warning("Subida de archivos no disponible: falta configurar OAuth de Drive "
                       "(ver SETUP_GOOGLE.md). El resto del caso funciona igual.")
        else:
            ac = st.columns([3, 4, 2])
            with ac[0]:
                ad_tipo = _tipo_con_otro("Tipo de archivo", cl.TIPOS_ADJUNTO,
                                         key=f"nad_tipo_{caso['id']}")
            ad_desc = ac[1].text_input("Descripción (ej. 'Telegrama de despido')",
                                       key=f"nad_desc_{caso['id']}")
            ad_fecha = ac[2].date_input("Fecha (ej. envío del telegrama)", value=None,
                                        format="DD/MM/YYYY", key=f"nad_fecha_{caso['id']}")
            archivos = st.file_uploader(
                "Archivos (PDF/imágenes) — podés elegir varios",
                type=["pdf", "jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True, key=f"nad_files_{caso['id']}")
            if st.button("⬆️ Subir", type="primary", key=f"upad_{caso['id']}"):
                if not archivos:
                    st.error("Elegí al menos un archivo.")
                else:
                    ok, fallaron = 0, []
                    total = len(archivos)
                    prog = st.progress(0.0, text=f"Subiendo 0/{total}…")
                    for i, f in enumerate(archivos, start=1):
                        try:
                            with st.spinner(f"⏳ Subiendo «{f.name}» ({i}/{total}) a Drive…"):
                                url = drive.subir_adjunto(
                                    f.getvalue(), f.name, f.type,
                                    prefijo=f"{caso.get('cliente','')}_{ad_tipo}")
                                db.append_adjunto({
                                    "caso_id": caso["id"], "tipo": ad_tipo,
                                    "descripcion": ad_desc.strip(),
                                    "fecha": cl.fmt_fecha(ad_fecha) if ad_fecha else "",
                                    "url": url,
                                })
                            ok += 1
                        except Exception as e:  # noqa: BLE001
                            fallaron.append(f"{f.name}: {e}")
                        prog.progress(i / total, text=f"Subiendo {i}/{total}…")
                    prog.empty()
                    _refrescar("adjuntos")
                    _limpiar_keys(f"nad_desc_{caso['id']}")
                    _limpiar_keys(f"nad_fecha_{caso['id']}")
                    _limpiar_keys(f"nad_files_{caso['id']}")
                    if fallaron:
                        st.warning(f"Subí {ok} archivo(s). Fallaron: " + " | ".join(fallaron))
                    st.session_state["toast_msg"] = f"{ok} archivo(s) subido(s) a Drive"
                    st.session_state["vc_ok"] = f"{ok} archivo(s) subido(s) ✅"
                    st.rerun()


# =============================================================================
# 📅 AGENDA (global)
# =============================================================================
elif seccion == "📅 Agenda":
    st.header("📅 Agenda — próximos vencimientos")

    cliente_por_caso = {c["id"]: c.get("cliente", "") for c in casos}
    enriquecidos = []
    for e in agenda:
        e2 = {**e, "cliente": cliente_por_caso.get(str(e.get("caso_id")), "")}
        enriquecidos.append(e2)
    evs = cl.proximos_eventos(enriquecidos, hoy)  # pendientes, ordenados

    n_venc = sum(1 for e in evs if e["codigo"] == "vencido")
    n_hoy = sum(1 for e in evs if e["codigo"] == "hoy")
    n_prox = sum(1 for e in evs if e["codigo"] == "proximo")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pendientes", len(evs))
    m2.metric("🔴 Vencidos", n_venc)
    m3.metric("🟠 Hoy", n_hoy)
    m4.metric("🟡 Próximos (≤7d)", n_prox)

    if cal.calendar_disponible():
        st.caption("✅ Los eventos se crean automáticamente en Google Calendar del estudio.")
    else:
        st.caption("ℹ️ Google Calendar automático no configurado. Descargá el .ics e "
                   "importalo una vez al calendario del celular para tener avisos.")

    if not evs:
        st.success("No hay vencimientos pendientes. 🎉")
    else:
        filas = []
        for e in evs:
            filas.append({
                "Estado": f"{e['emoji']} {e['etiqueta']}",
                "Fecha": e.get("fecha", ""),
                "Cliente": e.get("cliente", ""),
                "Tipo": e.get("tipo", ""),
                "Detalle": e.get("descripcion", ""),
            })
        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

    st.divider()
    ics = cal.construir_ics(evs, nombre_cal="Agenda Estudio")
    st.download_button(
        "⬇️ Descargar agenda (.ics) para el celular",
        ics.encode("utf-8"), file_name="agenda_estudio.ics", mime="text/calendar")


# =============================================================================
# ⬇️ EXPORTAR
# =============================================================================
elif seccion == "⬇️ Exportar":
    st.header("⬇️ Exportar")

    st.subheader("📄 Word")
    st.caption("Todos los casos en un solo documento Word (cada caso con sus datos, "
               "su agenda y sus adjuntos). Ideal para imprimir o archivar.")
    if casos:
        _word_todo = dx.exportar_todo(casos, eventos_por_caso, adjuntos_por_caso, hoy)
        st.download_button("📄 Descargar todos los casos (Word)", _word_todo,
                           file_name="Casos del estudio.docx", mime=dx.MIME)
    else:
        st.info("No hay casos para exportar.")

    st.divider()
    st.subheader("📊 Excel / CSV")
    st.caption("Para trabajar los datos en una planilla (Excel).")

    def _csv(filas, headers):
        df = pd.DataFrame([{k: f.get(k, "") for k in headers} for f in filas])
        return df.to_csv(index=False).encode("utf-8-sig")

    c1, c2, c3 = st.columns(3)
    c1.download_button("📋 Casos", _csv(casos, db.CASOS_HEADERS),
                       file_name="casos.csv", mime="text/csv")
    c2.download_button("📅 Agenda", _csv(agenda, db.AGENDA_HEADERS),
                       file_name="agenda.csv", mime="text/csv")
    c3.download_button("📎 Adjuntos", _csv(adjuntos, db.ADJUNTOS_HEADERS),
                       file_name="adjuntos.csv", mime="text/csv")


# =============================================================================
# 🗑️ BORRAR
# =============================================================================
elif seccion == "🗑️ Borrar":
    st.header("🗑️ Borrar")
    st.info("Borrar un **caso** elimina también sus eventos de agenda y sus adjuntos "
            "(y los eventos del Google Calendar). Pide la clave del estudio.")

    if "del_ok" in st.session_state:
        st.success(st.session_state.pop("del_ok"))

    if not casos:
        st.info("No hay casos para borrar.")
        st.stop()

    opciones = {"— Elegí un caso —": None}
    for c in sorted(casos, key=lambda x: x.get("cliente", "").lower()):
        opciones[_label_caso(c)] = c["id"]
    sel = st.selectbox("Caso a eliminar", list(opciones.keys()), key="del_sel")
    cid = opciones[sel]
    if cid:
        c = next((x for x in casos if x["id"] == cid), None)
        n_ev = len(eventos_por_caso.get(cid, []))
        n_ad = len(adjuntos_por_caso.get(cid, []))
        st.warning(
            f"Vas a **ELIMINAR** el caso de **{c.get('cliente','')}** "
            f"({c.get('rubro','')} · {c.get('area','')}) junto con "
            f"**{n_ev}** evento(s) de agenda y **{n_ad}** adjunto(s).")
        st.caption("Los archivos ya subidos a Drive no se borran de Drive (quedan accesibles "
                   "por su link, pero se quita su registro).")
        clave = st.text_input("Clave del estudio para confirmar", type="password", key="del_pwd")
        if st.button("🗑️ Eliminar caso", type="primary", key="del_btn"):
            if clave != _clave_app():
                st.error("Clave incorrecta. No se borró nada.")
            else:
                gcal_ids = db.borrar_caso(cid)
                for gid in gcal_ids:
                    cal.borrar_evento_calendar(gid)
                _refrescar()
                st.session_state.pop("caso_sel", None)
                st.session_state["del_ok"] = "Caso eliminado (con su agenda y adjuntos)."
                st.rerun()
