# H2O Quote RPA - Automated Quote Processing

## 📋 Overview

Sistema RPA (Robotic Process Automation) para automatizar el procesamiento de cotizaciones de seguros comerciales (Blue Quote PDFs). El sistema:
1. Monitorea emails con subject "Submission"
2. Extrae datos de PDFs (Blue Quote)
3. Clasifica tipo de negocio basado en commodities
4. Valida documentos adjuntos requeridos
5. Envía correos a las MGAs correspondientes con los documentos

## 🎯 Objetivo

Automatizar el flujo completo desde la recepción de un email con PDF de cotización hasta el envío de la solicitud a las MGAs correspondientes con todos los documentos requeridos.

## 📁 Estructura del Proyecto

```
H2O_Quote_RPA/
├── config/
│   └── CHECK LIST (2)_ESTANDARIZADO.xlsx  # Configuración de tipos de negocio y mensajes
├── data/
│   ├── input/          # PDFs entrantes (a procesar)
│   └── output/         # JSONs extraídos y logs
├── modules/
│   ├── __init__.py
│   ├── pdf_extractor.py      # Extracción de datos de PDFs (Blue Quote)
│   ├── commodity_matcher.py  # Fuzzy matching: commodity → tipo de negocio
│   ├── excel_config.py       # Lectura de configuración desde Excel
│   └── message_builder.py    # Construcción de mensajes según tipo
├── BlueQuote/
│   ├── extract_quote.py      # Script base de extracción (core)
│   └── *.pdf                 # PDFs de ejemplo/prueba
├── main.py                   # Orquestador principal del flujo
├── requirements.txt          # Dependencias Python
├── README.md                # Este archivo
└── ARCHITECTURE.md          # Documentación técnica detallada
```

## 🚀 Flujo de Procesamiento

```
1. Email recibido (subject: "Submission")
     ↓
2. pdf_extractor.py → Extrae commodity del BLUE QUOTE
     ↓
3. commodity_matcher.py → Identifica tipo de negocio (fuzzy matching)
     ↓
4. mga_reader.py → Obtiene lista de MGAs para ese tipo
     ↓
5. attachment_validator.py → Valida documentos requeridos
     ↓
6. Para cada MGA con documentos completos:
     → Envía email con adjuntos a la MGA
     ↓
7. Si ninguna MGA recibió email → Envía fallback
```

## 📦 Módulos Principales

### ✅ Implementados

| Módulo | Descripción |
|--------|-------------|
| `pdf_extractor.py` | Extrae datos de PDFs Blue Quote |
| `commodity_matcher.py` | Fuzzy matching: commodity → tipo de negocio |
| `comm_tdn_mapper.py` | Mapea commodity a tipo de negocio vía Excel |
| `mga_reader.py` | Lee MGAs del Excel según tipo de negocio |
| `mga_email_reader.py` | Lee emails de MGAs desde hoja MAILS APPs |
| `attachment_validator.py` | Valida documentos adjuntos requeridos |
| `email_receiver.py` | Monitoreo de inbox IMAP |
| `email_sender.py` | Envío de emails SMTP con adjuntos |
| `email_template_builder.py` | Construcción de respuestas |
| `config_manager.py` | Gestor de configuración centralizada |

### 📝 Documentos Requeridos

Para enviar a MGAs, el email debe contener:
- `BLUE QUOTE` - Cotización (requerido)
- `MVR` - Motor Vehicle Report (requerido)
- `CDL` - Commercial Driver License (requerido)
- `IFTAS` - Registro IFTA (requerido)
- `LOSS RUN` - Historial de pérdidas (requerido)
- `NEW VENTURE APP` - Aplicación (o `NEW VENTURE APP INVO` para MGA INVO)

## 🛠️ Tecnologías

- **Python 3.x**
- **pdfplumber**: Extracción de PDFs
- **openpyxl**: Lectura de Excel
- **difflib/fuzzywuzzy**: Fuzzy matching
- (Futuro) **Exchange/SMTP**: Email automation

## 📝 Convenciones de Código

- **Modularidad**: Un módulo = Una responsabilidad
- **Nombres descriptivos**: `commodity_matcher.py` no `utils.py`
- **Funciones pequeñas**: Max 50 líneas por función
- **Type hints**: Siempre que sea posible
- **Docstrings**: Todas las funciones públicas

## 🔧 Configuración

### Variables de entorno (`.env`, NO commitear)

```env
# --- Email / Gmail API ---
EMAIL_USERNAME=programacion@h2oins.com      # usado por IMAP/SMTP legacy y como impersonate de Drive
EMAIL_PASSWORD=your_app_password
EMAIL_ANALYSIS_TO=quotes@h2oins.com         # destino del correo de análisis del bot
TEST_EMAIL_OVERRIDE=test@example.com        # para pruebas
DRY_RUN=True                                # True=simular, False=enviar real

# --- MGAs RPA ---
GEICO_QUEUE_ENABLED=true                    # GEICO ON/OFF en la cola (Progressive siempre ON)
GEICO_HEADLESS=true                         # headless (obligatorio en Docker)
PROGRESSIVE_HEADLESS=true

# --- Google Drive (subida opcional de PDFs) ---
DRIVE_MAIN_FOLDER_ID=your_drive_folder_id           # carpeta destino de los PDFs
DRIVE_IMPERSONATE_USER=programacion@h2oins.com      # impersona vía DWD; si no hay DWD cae a Service Account
DRIVE_ALLOW_SERVICE_ACCOUNT_FALLBACK=True

# --- Proxy IA (clasificador de commodities) ---
OPENAI_BASE_URL=http://localhost:3000/v1            # en Docker: http://host.docker.internal:3000/v1
```

### 🔑 Credenciales de Google — son TRES distintas (no confundir)

| Propósito | Tipo | Cuenta / Proyecto | Archivo(s) | Cómo obtenerlo |
|-----------|------|-------------------|------------|----------------|
| **Leer/responder/etiquetar el inbox** | OAuth de usuario (Gmail API, scope `gmail.modify`) | `quotes@h2oins.com` / proyecto del cliente OAuth de Gmail | `data/credentials.json` (cliente OAuth) + `data/token.json` (token) | `python scripts/gmail_oauth_bootstrap.py` (consiente como **quotes@**) |
| **Sync de reglas desde Drive** (descarga `REGLAS FINALES`) | OAuth de usuario (Drive, scope `drive.readonly`) | `programacion@h2oins.com` / proyecto **drivequotes** | `config/oauth-credentials.json` (cliente OAuth) + `config/oauth_user_token.json` (token) | `python tools/read_sheet_as_user.py` (consiente como **programacion@**) |
| **Subir PDFs de cotizaciones a Drive** (OPCIONAL) | **Service Account** (Drive, scope `drive`) | SA del proyecto **drivequotes** (`csquotes@drivequotes.iam.gserviceaccount.com`) | `config/drivequotes-<KEY_ID>.json` | ver abajo |

> ⚠️ **El token OAuth es por-cuenta; el cliente OAuth es por-proyecto.** El sync de reglas DEBE consentirse como `programacion@` en el proyecto `drivequotes`, y el inbox como `quotes@`. Mezclarlos da errores 403 "API not enabled in project …".

### 📍 Ubicaciones de archivos sensibles (TODOS gitignored)

| Archivo | Qué es |
|---------|--------|
| `.env` | Variables/credenciales de entorno |
| `data/credentials.json` · `data/token.json` | OAuth de Gmail API (**quotes@**) |
| `config/oauth-credentials.json` · `config/oauth_user_token.json` | OAuth de Drive sync (**programacion@**) |
| `config/drivequotes-<KEY_ID>.json` | **Service Account** de subida a Drive (proyecto drivequotes) |
| `data/progressive_session.json` · `data/geico_session.json` | Sesiones de navegador persistidas |
| `data/bot_since_epoch.txt` | Corte por fecha del bot (no procesa correos anteriores) |

`.gitignore` cubre `.env`, `config/*.json`, `data/credentials.json`, `data/token.json`, sesiones, etc. Verificá con `git check-ignore <archivo>` antes de commitear.

### 🛰️ Service Account para subir PDFs a Drive (opcional)

Sin esto el bot **cotiza y responde igual**, solo no sube los PDFs a Drive. Para habilitarlo:

1. **Google Cloud Console** → proyecto **drivequotes** → *IAM y administración → Cuentas de servicio*.
2. Usar/crear la SA `csquotes@drivequotes.iam.gserviceaccount.com` → pestaña **Claves → Crear clave nueva → JSON**. Se descarga `drivequotes-<KEY_ID>.json` (el `<KEY_ID>` cambia en cada descarga).
3. Dejar el archivo en `config/drivequotes-<KEY_ID>.json` y apuntar la config:
   `config/settings.yaml` → `drive.credentials_path: "config/drivequotes-<KEY_ID>.json"`.
4. **Dar acceso de escritura al SA sobre el destino** (`DRIVE_MAIN_FOLDER_ID`):
   - Si es una **carpeta de My Drive** (ID empieza con `1…`): compartirla con `csquotes@drivequotes.iam.gserviceaccount.com` como **Editor**.
   - Si es una **Unidad Compartida / Shared Drive** (ID empieza con `0A…`, **este es el caso actual**: `0ALmdSjy0qv6gUk9PVA`): agregar al SA como **miembro** de la unidad con rol **Administrador de contenido** (Content Manager) o **Colaborador**.
5. Reiniciar el bot. En el log debe verse `Drive: Authenticated as … (service account)` (o `(delegated user)` si hay Domain-Wide Delegation configurada para impersonar `programacion@`).

> El código ya pasa `supportsAllDrives=True`, así que sube tanto a My Drive como a Shared Drives.
> El modo **delegación (DWD)** sube como `programacion@`; requiere autorizar el client_id de la SA con el scope `drive` en el Admin de Google Workspace. Si no está configurado, el bot intenta delegar, falla, y **cae a Service Account** (sube como la propia SA). Para una Shared Drive **no hace falta DWD** — basta el paso 4.

### Excel de configuración

- `config/CHECK LIST (2)_ESTANDARIZADO.xlsx` — checklist de docs requeridos por MGA.
- Reglas de elegibilidad: hoja **`REGLAS FINALES`** (la baja el sync de Drive a `config/REGLAS_quotes.xlsx`).

## 🐳 Ejecución del bot autónomo (Docker)

El bot corre en **un contenedor** (incluye el RPA de Playwright, headless):

```bash
docker compose build          # construir la imagen
docker compose up -d          # arrancar (restart: unless-stopped)
docker compose logs -f        # ver en vivo
docker compose ps             # estado / healthcheck
docker compose down           # apagar
```

- El proxy de IA (clasificador de commodities) debe estar **arriba en el host** en el puerto `3000` (el contenedor lo alcanza por `host.docker.internal:3000`).
- **Sesión única por MGA:** NO correr el runner en el host (`python -m modules.quote_queue.runner`) y el contenedor a la vez.
- Volúmenes montados (RW): `./config`, `./data`, `./logs`.

### 📧 Comportamiento con los correos

- El bot lee **no-leídos** con asunto `Submission` recibidos **después** del corte (`data/bot_since_epoch.txt`); el backlog viejo no se toca.
- **Servicio transparente:** el bot NO etiqueta, NO marca leído y NO responde en el hilo de ventas. El correo original queda exactamente como llegó para el equipo humano. La dedup contra reprocesamiento es por Gmail message-id en `seen_emails` (cola SQLite), no por etiquetas.
- Al **cotizar**, el bot envía un correo **nuevo** (sin hilo, sin CC) a `EMAIL_ANALYSIS_TO` con el análisis, el "por qué" del rule engine y la tabla "Decisiones tomadas" (Decision Ledger), y adjunta los PDFs.

## 📚 Documentación Adicional

Ver [ARCHITECTURE.md](ARCHITECTURE.md) para detalles técnicos de cada módulo.

## 🤝 Ejecución

```bash
# Bot autónomo (entrypoint real): monitor de inbox + workers por MGA
python -m modules.quote_queue.runner
# …o en Docker (recomendado en producción):
docker compose up -d

# Tests
python -m pytest -q
```

> El entrypoint del bot es `modules/quote_queue/runner.py` (lo usa el Dockerfile).
> `workflow_orchestrator.py` ya NO se corre directo (es una librería del pipeline).

---

**Última actualización**: 2026-06-25  
**Versión**: 0.4.0 (Bot autónomo Gmail API + Dockerizado + Progressive/GEICO RPA)
