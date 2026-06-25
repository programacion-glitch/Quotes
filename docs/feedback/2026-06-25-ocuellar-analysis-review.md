# Feedback Diana Rubio — Análisis O CUELLAR LLC (USDOT 1962157)

- **Cliente:** O CUELLAR LLC · USDOT 1962157 · TX · owner OZIEL CUELLAR
- **Perfil (Blue Quote):** commodity DIRT/SAND/GRAVEL · carrier actual PROGRESSIVE COUNTY MUTUAL · radio 100 millas · **2 power units** (2012 KW, 2007 KW Tractor Truck) + **2 trailers** (End Dump) · 3 drivers · usa MTC + APD
- **Directiva del usuario:** "Ajusta lo que podamos, lo que no esté en nuestros desarrollos no hacerlo."

## Triage (verificado contra el código)

Leyenda: 🟢 accionable en nuestro código · ⚙️ cambio de config (Excel REGLAS) · 🟡 reglas (necesita criterio de Diana) · 🔴 fuera (MGA sin automatización / feature nueva) · ✅ ya funciona

| # | Punto Diana | Estado | Detalle técnico |
|---|-------------|--------|-----------------|
| 1a | GEICO declinado NO debe salir como "disponible" | 🟢 | El email categoriza por rule_engine; un web-MGA (GEICO) puede salir "elegible" por reglas aunque el RPA lo haya DECLINADO. Falta reconciliar el resultado RPA → moverlo a "no elegibles". `analysis_email_builder.py` + orquestador |
| 1b | Dejar imagen como evidencia del decline GEICO | 🟢 | El screenshot YA se captura (`geico/quote_flow` halt) y se guarda en DB, pero NO se adjunta al correo (`worker.py:187` solo adjunta PDFs). Agregar screenshot a adjuntos |
| 2 | Progressive excluido por ser carrier actual | ✅ | Ya funciona (elogio de Diana) |
| 3 | "No elegibles" solo las que realmente no aplican (operación/años/exp) | 🟡 | Afinar reglas por MGA en REGLAS FINALES — necesita criterio de Diana |
| 4 | Berkshire: online, enviar indicación "sujeto a: loss runs + CDL 2 años" | 🔴 | No hay automatización Berkshire; "online/sujeto a" es concepto nuevo (no existe en rule_engine) |
| 5 | Futuristics: enrolar en TruckerCloud antes de cotizar | 🔴 | No modelado; no hay automatización Futuristics |
| 6 | Unidades = solo power units (2), no 4 (trailers aparte) | 🟡 | El extractor ya tiene flag `is_trailer`; `units.count` suma todo. Mostrar power units = display (seguro); usarlo en MIN_UNITS = cambio de reglas |
| 7 | Rocklake: MTC+APD, pérdidas, MVR 5 años, online → cotizar+indicación | 🔴 | No hay automatización Rocklake |
| 8 | Reglas por compañía (TUMI frequency calc, Great West app) mencionarlas | ⚙️/🟡 | Columna NOTAS_EXTRA existe (informativa). Requiere poblar Excel + render en análisis |
| 9 | Jencap: ya no se ofrece → quitar del análisis | ⚙️ | Jencap está en REGLAS FINALES (18 tipos). Quitar = borrar/excluir sus filas (cambio en el Excel de reglas) |
| 10 | County Hall / Paramount: Paramount enviar preguntas diligenciadas | 🔴 | Feature/rules; no hay automatización |

## Conclusión

**Accionable en nuestros desarrollos (sin tocar lógica de elegibilidad de reglas):**
- **1b** — adjuntar el screenshot del decline de GEICO al correo (evidencia). Bajo riesgo, puro reporting.
- **1a** — que GEICO declinado por el RPA NO aparezca como "elegible/disponible" en el análisis (reconciliar resultado RPA). Reporting.

**Cambio de config (Excel REGLAS), si se autoriza tocar reglas:**
- **9** — quitar Jencap.

**Fuera (no está en nuestros desarrollos):** 4 Berkshire, 5 Futuristics, 7 Rocklake, 10 Paramount/County Hall (sin automatización), 3 y 8 (afinar reglas — necesita criterio de Diana), 6-MIN_UNITS (reglas).
