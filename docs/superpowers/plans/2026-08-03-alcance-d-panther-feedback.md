# Alcance D — Feedback Diana 2026-08-03 (PANTHER): features nuevos

Semilla de plan. Estos 4 pedidos NO son fixes del flujo actual sino alcance
nuevo; cada uno necesita brainstorming/spec propio antes de implementar.

## D1 — Analizar también negocios con experiencia (no solo New Venture)

Diana: "necesito que haga el análisis cuando tiene varios años en el negocio
para poder hacerte comentarios al respecto."

- Hoy el runner filtra remitentes RT (5) y NEW_VENTURE (11) y el subject
  filter es "Submission" — verificar si el corte real es por remitente o si
  los Submission de negocios con años ya entran y se procesan.
- El rule engine ya distingue NV/establecidos (IS_NEW_VENTURE, MIN_BUSINESS_YEARS,
  loss run, MVR años). Las correcciones de Diana 2026-08-03 dejaron los paths
  de establecidos poblados (Great West 2+, SGA 3+, etc.).
- Decisión pendiente del usuario: ¿se habilita ya o tras validar NV en vivo?

## D2 — Excel de prospectos New Sales

Diana: marcar al cliente en el excel de prospectos (captura: fila
KELLY | 5527168 | OTHER | Keep On Rolling Inc bajo "LUNES 03 DE AGOSTO DE 2026").

- Preguntas: ¿dónde vive ese excel (Drive id)?, ¿quién más lo edita
  (conflictos)?, ¿qué columnas exactas llena el bot y con qué valores?
- Riesgo: es un archivo operativo del equipo de ventas — escribir con
  cuidado (append a la fecha correcta, no tocar filas ajenas).

## D3 — Estructura de carpetas del cliente (Drive)

Diana: verificar si la carpeta del cliente existe; si existe, crear subcarpeta
con el AÑO que se está cotizando; adentro: los documentos adjuntos de la línea
de correo + subcarpeta "quotes" con las cotizaciones guardadas con el formato
indicado (ver D4).

- Ya existe DriveManager (uploads a '1) QUOTES' de quotes@) — extenderlo.
- Preguntas: ¿raíz de carpetas de clientes?, ¿naming de la carpeta cliente
  (business name? USDOT?), ¿qué pasa si no existe: crearla o avisar?

## D4 — Nombre del PDF de Progressive con fecha AAAA-MM-DD

Diana: la cotización de Progressive debe imprimirse/guardarse con fecha
año-mes-día, no el nombre por defecto de la página.

- Registrado como R-086 (VIGENTE) en config/mga_decision_rules.xlsx.
- ✅ IMPLEMENTADO 2026-08-03: `quote_pdf_basename` en pdf_downloader.py —
  `AAAA-MM-DD {negocio} Progressive {quote#}.pdf` (la descarga del PDF
  oficial ya existía desde julio). Falta solo el destino final: la
  subcarpeta "quotes" del cliente (D3).

## Relacionado pero NO alcance D (ya en curso)

- Berkshire como plataforma web a automatizar (Diana pt. 11) — tercera MGA
  web; evaluar después de estabilizar Progressive+GEICO.
- Camiones >15 años: relevar qué MGAs tienen tope de edad (hoy solo Paramount
  anotado) — agenda de la sesión con Diana junto con las 65 filas EN-DUDA.
