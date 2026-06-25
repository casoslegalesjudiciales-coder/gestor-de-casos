# ⚖️ Gestor de Casos

App web para un estudio jurídico: controlar casos y **no perder audiencias ni
plazos procesales**. Pensada para usarse desde la compu o el celular.

## Qué hace
- Carga de **casos** clasificados en 2 rubros (**Extrajudicial** / **Judicial**)
  × 4 áreas (**Despido / ART / Accidente de Tránsito / Otros**). Cada área pide
  sus propios campos (el formulario se adapta solo).
- **Agenda** por caso: audiencias, plazos y recordatorios con **semáforo**
  (🔴 vencido · 🟠 hoy · 🟡 próximo · 🟢 futuro) y alta automática en
  **Google Calendar** (+ archivo **.ics** de respaldo para el celular).
- **Adjuntos**: telegramas (con fecha de envío), dictámenes, altas/rechazos,
  fotos de daños y lesiones, expediente, sentencia — guardados en Google Drive.
- Acceso con **una clave compartida** del estudio.

## Arquitectura (resumen)
| Archivo | Rol |
|---|---|
| `app.py` | Interfaz (Streamlit): portón, listado, alta, edición, agenda, exportar, borrar. |
| `casos_logic.py` | Lógica pura: clasificación, `SCHEMA` de campos por área, fechas, montos, semáforo. |
| `casos_db.py` | Base de datos en Google Sheets (pestañas Casos / Agenda / Adjuntos). |
| `drive_casos.py` | Subida de adjuntos a Drive (vía OAuth de la cuenta del estudio). |
| `calendar_db.py` | Recordatorios: Google Calendar (push) + generación de `.ics`. |
| `oauth_creds.py` | Credenciales OAuth (Drive + Calendar). |
| `gen_oauth_token.py` | Script de un solo uso para generar el token OAuth. |

Datos en Google Sheets; archivos en Google Drive; recordatorios en Google
Calendar. **Todo bajo la cuenta del estudio.**

## Puesta en marcha
1. Seguí **[SETUP_GOOGLE.md](SETUP_GOOGLE.md)** (crear cuentas y conectar Google).
2. Completá `.streamlit/secrets.toml` (a partir de `.streamlit/secrets.toml.example`).
3. Probá local:
   ```
   pip install -r requirements.txt
   streamlit run app.py
   ```
4. Publicá en Streamlit Cloud (último paso del SETUP).

## Notas
- El formulario muestra sólo los campos del área elegida. Para agregar o cambiar
  campos de un área, se edita el diccionario `SCHEMA` en `casos_logic.py` (y, si es
  un campo nuevo, se agrega su columna a `CASOS_HEADERS` en `casos_db.py`).
- Si OAuth no está configurado, la app igual funciona: la carga de archivos y el
  Calendar automático quedan en pausa, pero casos, agenda, semáforo y `.ics` andan.
- **Antes de entregar:** cambiar `app_password`.
