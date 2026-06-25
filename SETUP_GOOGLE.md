# Setup de Google — Gestor de Casos (paso a paso)

Esta app guarda los datos en una **cuenta Google nueva, propia del estudio**. Hay
que crear esa cuenta y conectar tres servicios de Google: **Sheets** (la base de
datos), **Drive** (los archivos adjuntos) y **Calendar** (los recordatorios).

> Glosario rápido:
> - **Cuenta de servicio (SA):** una "cuenta robot" que usa la app para escribir
>   en el Sheet sin que nadie inicie sesión. No tiene espacio de Drive propio.
> - **OAuth:** una autorización que das una sola vez con la cuenta del estudio
>   para que la app maneje **sus** archivos de Drive y **su** Calendar.
> - **secrets.toml:** el archivo donde van todas las claves (no se sube a GitHub).

Hacelo en este orden. Tomá nota de los IDs que te va pidiendo.

---

## 1) Crear la cuenta Gmail del estudio
- Andá a https://accounts.google.com/signup y creá una cuenta, ej.
  `estudio.jona@gmail.com`. **Toda la información del estudio va a vivir acá.**

## 2) Crear el proyecto en Google Cloud
- Iniciá sesión con esa cuenta en https://console.cloud.google.com
- Arriba, **Seleccionar proyecto → Proyecto nuevo** → nombre `gestor-casos` → Crear.
- Con el proyecto seleccionado, andá a **APIs y servicios → Biblioteca** y
  **habilitá** estas tres: **Google Sheets API**, **Google Drive API**,
  **Google Calendar API** (buscás cada una y "Habilitar").

## 3) Crear la cuenta de servicio (para el Sheet)
- **APIs y servicios → Credenciales → Crear credenciales → Cuenta de servicio**.
- Nombre: `gestor-casos`. Crear y continuar → Listo.
- Entrá a la cuenta de servicio recién creada → pestaña **Claves → Agregar clave →
  Crear clave nueva → JSON**. Se descarga un archivo `.json`.
- Guardalo en `C:\Users\lquinones\.secrets\` (o donde prefieras). **No lo subas a
  GitHub.** Anotá el email de la cuenta de servicio (termina en
  `...iam.gserviceaccount.com`).

## 4) Crear el Google Sheet (la base de datos)
- Con la cuenta del estudio, andá a https://sheets.google.com y creá una planilla
  **en blanco**, ponele nombre `Gestor de Casos - Base`.
- Botón **Compartir** → pegá el email de la cuenta de servicio (paso 3) →
  permiso **Editor** → Enviar.
- Copiá el **ID del Sheet**: está en la URL, entre `/d/` y `/edit`
  (`https://docs.google.com/spreadsheets/d/`**`ESTE_ES_EL_ID`**`/edit`).
- *(No hace falta crear pestañas: la app crea Casos/Agenda/Adjuntos sola al arrancar.)*

## 5) Crear las credenciales OAuth (Drive + Calendar)
- **APIs y servicios → Pantalla de consentimiento de OAuth**:
  - Tipo de usuario: **Externo** → Crear.
  - Completá nombre de la app (`Gestor de Casos`) y tu email.
  - En **Permisos/Scopes** podés dejarlo vacío (la app pide los suyos al
    autorizar).
  - **Importante:** en **Estado de publicación**, elegí **Publicar la app →
    Producción**. (Si la dejás en "Prueba", la autorización caduca a los 7 días.)
- **Credenciales → Crear credenciales → ID de cliente de OAuth**:
  - Tipo de aplicación: **App de escritorio** → Crear.
  - **Descargar JSON** → guardalo como `client_secret.json` en la carpeta del
    proyecto (al lado de `gen_oauth_token.py`).
- Generá el token (una sola vez), desde la carpeta del proyecto:
  ```
  pip install google-auth-oauthlib
  python gen_oauth_token.py client_secret.json
  ```
  Se abre el navegador → **iniciá sesión con la cuenta del estudio** → si aparece
  "app no verificada": *Configuración avanzada → Continuar* → Aceptar.
  El script imprime `oauth_client_id`, `oauth_client_secret` y
  `oauth_refresh_token`. **Copialos.**

## 6) Crear el calendario del estudio
- Con la cuenta del estudio en https://calendar.google.com → panel izquierdo →
  **Otros calendarios (+) → Crear calendario** → nombre `Agenda Estudio` → Crear.
- Entrá a **Configuración** de ese calendario → bajá hasta **Integrar calendario**
  → copiá el **ID de calendario** (suele terminar en `@group.calendar.google.com`).
- *(El recordatorio le va a llegar a quien tenga ese calendario agregado en su
  Google Calendar del celular.)*

## 7) Cargar todo en secrets.toml
- Copiá `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml` y completá:
  - `app_password` (clave de acceso del estudio — **cambiala**),
  - `sheets_id` (paso 4),
  - `[gcp_service_account]` (pegá el contenido del JSON del paso 3),
  - `oauth_client_id` / `oauth_client_secret` / `oauth_refresh_token` (paso 5),
  - `calendar_id` (paso 6),
  - `drive_folder_id` (opcional; vacío = los archivos van a la raíz del Drive).

## 8) Probar localmente
```
pip install -r requirements.txt
streamlit run app.py
```
Abrí http://localhost:8501, ingresá la clave, creá un caso de prueba, cargale una
audiencia (verificá que aparezca en Google Calendar) y un archivo (verificá que
aparezca en Drive).

## 9) Publicar en internet (Streamlit Cloud)
- Subí **toda la carpeta** a un repositorio de GitHub **excepto** los secretos
  (el `.gitignore` ya excluye `secrets.toml`, `*.json` y `.env`).
- En https://share.streamlit.io → **New app** → elegí el repo → Main file: `app.py`.
- En **Settings → Secrets**, pegá el contenido de tu `secrets.toml`.
- En **Settings → Python version**, elegí **3.12**.
- Deploy. Tras cualquier cambio de código o secrets: **Manage app → ⋮ → Reboot**.

Listo: te queda un link `*.streamlit.app` + la clave para todo el estudio.
