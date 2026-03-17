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

Archivo `.env`:
```env
EMAIL_USERNAME=your_email@example.com
EMAIL_PASSWORD=your_app_password
TEST_EMAIL_OVERRIDE=test@example.com  # Para pruebas
DRY_RUN=True  # True=simular, False=enviar real
DRIVE_MAIN_FOLDER_ID=your_drive_folder_id
DRIVE_IMPERSONATE_USER=workspace_user@yourdomain.com
DRIVE_ALLOW_SERVICE_ACCOUNT_FALLBACK=True
```

Excel de configuración:
- `config/CHECK LIST (2)_ESTANDARIZADO.xlsx`
  - Hoja `MAILS APPs`: Emails de MGAs (TO, CC)
  - Otras hojas: Tipos de negocio, reglas, MGAs

## 📚 Documentación Adicional

Ver [ARCHITECTURE.md](ARCHITECTURE.md) para detalles técnicos de cada módulo.

## 🤝 Ejecución

```bash
# Monitorear emails (modo producción)
python workflow_orchestrator.py

# Ejecutar tests de componentes
python test_mga_forwarding.py
```

---

**Última actualización**: 2026-02-07  
**Versión**: 0.2.0 (MGA Forwarding)
