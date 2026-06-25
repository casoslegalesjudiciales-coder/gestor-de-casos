"""gen_oauth_token.py — Generador (UNA sola vez) del refresh token OAuth.

Se corre LOCALMENTE en la compu de quien arma el estudio. Abre el navegador para
que inicies sesión con la **cuenta Gmail del estudio** y autorices la app a
manejar sus archivos de Drive (drive.file) y su Calendar (calendar.events).
Al final imprime los tres valores que van a `.streamlit/secrets.toml`:
  oauth_client_id, oauth_client_secret, oauth_refresh_token

Requisitos:
  pip install google-auth-oauthlib
  Tener el archivo client_secret JSON descargado de Google Cloud Console
  (Credenciales → ID de cliente OAuth → tipo "App de escritorio").

Uso:
  python gen_oauth_token.py [ruta_al_client_secret.json]
  (por defecto busca 'client_secret.json' en esta carpeta)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar.events",
]


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
    p = Path(ruta)
    if not p.exists():
        print(f"[ERROR] No encuentro el archivo de credenciales: {p}")
        print("  Descargalo de Google Cloud Console -> Credenciales -> ID de cliente "
              "OAuth (App de escritorio) y pasa su ruta como argumento.")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(p), SCOPES)
    print("Se va a abrir el navegador. Inicia sesion con la CUENTA DEL ESTUDIO y acepta.")
    print("(Si Google muestra 'app no verificada': Configuracion avanzada -> Continuar.)")
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        print("[ERROR] No se obtuvo refresh_token. Volve a intentar revocando el acceso previo "
              "en https://myaccount.google.com/permissions y corré de nuevo este script.")
        sys.exit(1)

    info = json.loads(p.read_text(encoding="utf-8"))
    bloque = info.get("installed") or info.get("web") or {}
    client_id = bloque.get("client_id", "")
    client_secret = bloque.get("client_secret", "")

    print("\n" + "=" * 70)
    print("[OK] LISTO. Pega esto en .streamlit/secrets.toml (o en .env en mayusculas):\n")
    print(f'oauth_client_id     = "{client_id}"')
    print(f'oauth_client_secret = "{client_secret}"')
    print(f'oauth_refresh_token = "{creds.refresh_token}"')
    print("=" * 70)


if __name__ == "__main__":
    main()
