# Setup OAuth User Credentials para leer Drive como tu cuenta

Necesario una sola vez. Después el token se refresca solo.

## Pasos (5 min)

### 1. Abre el proyecto GCP correcto

Ve a https://console.cloud.google.com/ y selecciona el proyecto **`drivequotes`** (el mismo donde está el Service Account `csquotes`).

### 2. Habilita la Drive API (si no está)

`APIs & Services` → `Library` → busca "Google Drive API" → si dice "Enable", dale.

### 3. Configura el OAuth Consent Screen (si nunca lo hiciste)

`APIs & Services` → `OAuth consent screen`:

- **User Type**: **Internal** (recomendado, solo cuentas de h2oins.com pueden autenticar)
  - Si no aparece "Internal", elige **External** y abajo añade `programacion@h2oins.com` como **Test User**
- **App name**: `H2O Quotes Internal` (o lo que quieras)
- **User support email**: `programacion@h2oins.com`
- **Developer contact**: `programacion@h2oins.com`
- **Save and continue** hasta el final (no necesitas añadir scopes en la consent screen)

### 4. Crea el OAuth Client

`APIs & Services` → `Credentials` → `+ Create Credentials` → `OAuth client ID`:

- **Application type**: **Desktop app**
- **Name**: `H2O Quotes Local Reader`
- Click **Create**

### 5. Descarga el JSON

En la lista de OAuth 2.0 Client IDs, busca el que acabas de crear → click el botón de descarga (↓) → guarda el archivo como:

```
C:\Users\Desarrollo\Videos\Quotes\H2O_Quote_RPA\config\oauth_client.json
```

> Nota: este archivo NO contiene secretos críticos (los OAuth Desktop clients son públicos por diseño), pero igual está cubierto por `.gitignore` (`config/*.json`).

### 6. Ejecuta el script

```bash
python tools/read_sheet_as_user.py
```

La primera vez:
- Se abre tu navegador
- Loguéate como **`programacion@h2oins.com`**
- Acepta los permisos (Drive read-only)
- Verás "The authentication flow has completed" en el navegador
- El script imprime la lista de hojas del archivo

Las siguientes veces no abre browser (usa el refresh token guardado en `config/oauth_user_token.json`).

## ¿Por qué este flujo y no SA / Drive MCP?

- **Service Account** falló porque el Workspace bloquea sharing externo (Drive convierte el share en "request access" que el SA nunca acepta).
- **Drive MCP de Claude** falló por la política "AI ineligibility" aplicada al archivo.
- **OAuth como usuario** te autentica como tú mismo contra Google Drive API directa — no pasa por filtros AI ni por restricciones de external sharing.

## Troubleshooting

**Error: `redirect_uri_mismatch`** → asegúrate que elegiste "Desktop app" (no "Web app") al crear el client.

**Error: `access_denied`** → la cuenta con la que te logueaste no está en la lista de Test Users (si el consent screen es External). Vuelve al consent screen y añádela.

**Error: `invalid_grant: Token has been expired or revoked`** → borra `config/oauth_user_token.json` y vuelve a correr el script para reautenticar.
