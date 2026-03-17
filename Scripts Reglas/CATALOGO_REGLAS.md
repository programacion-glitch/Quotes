# Catálogo de Reglas Estandarizadas

Este documento describe todos los códigos utilizados en la columna `REGLA_ESTANDARIZADA` del archivo Excel.

## Formato

Las reglas se combinan usando el separador `|` (pipe). Ejemplo:
```
CDL_YEARS_2|MVR|PERDIDAS_SI_APLICA|IFTAS_SI_APLICA
```

---

## Categorías de Códigos

### 📋 CATEGORIA A: Requisitos de Experiencia y Documentación

| Código | Descripción | Ejemplo |
|--------|-------------|---------|
| `CDL_YEARS_<N>` | CDL con N años de experiencia demostrable | `CDL_YEARS_2` |
| `CDL_REQUIRED` | CDL requerido (sin años específicos) | `CDL_REQUIRED` |
| `MVR_YEARS_<N>` | MVR de N años | `MVR_YEARS_5` |
| `MVR` | MVR general requerido | `MVR` |
| `PERDIDAS_SI_APLICA` | Pérdidas si aplica | `PERDIDAS_SI_APLICA` |
| `PERDIDAS_LIMPIAS` | Pérdidas limpias requeridas | `PERDIDAS_LIMPIAS` |
| `PERDIDAS_<N>_AÑOS` | N años de pérdidas requeridos | `PERDIDAS_5_AÑOS` |
| `IFTAS_SI_APLICA` | IFTAS si aplica | `IFTAS_SI_APLICA` |
| `EIN_REQUIRED` | EIN requerido | `EIN_REQUIRED` |
| `REGISTRACIONES` | Registraciones requeridas | `REGISTRACIONES` |

### 🏢 CATEGORIA B: Requisitos del Negocio

| Código | Descripción | Ejemplo |
|--------|-------------|---------|
| `BUSINESS_YEARS_<N>+` | N o más años en el negocio | `BUSINESS_YEARS_3+` |
| `MIN_UNITS_<N>` | Mínimo N unidades | `MIN_UNITS_5` |
| `SOLO_NICO` | Solo con NICO | `SOLO_NICO` |
| `NV_SOLO_NICO` | New Venture solo con NICO | `NV_SOLO_NICO` |
| `NV_SPECIAL_REQUIREMENTS` | New Venture con requisitos especiales | `NV_SPECIAL_REQUIREMENTS` |
| `POLIZA_ACTIVA` | Requiere póliza activa | `POLIZA_ACTIVA` |

### 🚫 CATEGORIA C: Restricciones y Condiciones

| Código | Descripción | Ejemplo |
|--------|-------------|---------|
| `NO_BOTADERO` | No ir al botadero | `NO_BOTADERO` |
| `NO_DUMP` | No dump | `NO_DUMP` |
| `NO_REEFER` | No reefer | `NO_REEFER` |
| `NO_MTC` | No MTC | `NO_MTC` |
| `NO_FERTILIZANTES` | No fertilizantes | `NO_FERTILIZANTES` |
| `SOLO_LOCAL` | Solo local | `SOLO_LOCAL` |
| `SOLO_TRUCK_TRAILER` | Solo truck y trailer | `SOLO_TRUCK_TRAILER` |
| `SOLO_FLOTAS` | Solo en flotas | `SOLO_FLOTAS` |

### 📄 CATEGORIA D: Coberturas Específicas

| Código | Descripción | Ejemplo |
|--------|-------------|---------|
| `COVERAGE_<TIPOS>` | Coberturas específicas | `COVERAGE_APD,MTC,GL` |
| `COVERAGE_AL` | Solo Auto Liability | `COVERAGE_AL` |
| `COVERAGE_DUAL` | Solo DUAL | `COVERAGE_DUAL` |

### 💰 CATEGORIA E: Requisitos Financieros

| Código | Descripción | Ejemplo |
|--------|-------------|---------|
| `DOWN_<N>%` | Down payment de N% | `DOWN_25%` |
| `MIN_PRICE_<N>K` | Precio mínimo de $N mil | `MIN_PRICE_25K` |
| `SURCHARGE_<N>%` | Sobrecargo de N% | `SURCHARGE_10%` |

### 📝 CATEGORIA F: Formularios y Aplicaciones

| Código | Descripción | Ejemplo |
|--------|-------------|---------|
| `APP_DILIGENCIADA` | Aplicación diligenciada | `APP_DILIGENCIADA` |
| `PREGUNTAS_REQUIRED` | Preguntas requeridas | `PREGUNTAS_REQUIRED` |
| `PREGUNTAS_AUTO_HAULER` | Preguntas Auto Hauler | `PREGUNTAS_AUTO_HAULER` |
| `PREGUNTAS_UIIA` | Preguntas UIIA | `PREGUNTAS_UIIA` |
| `FORM_<ID>` | Formulario específico | `FORM_5C` |

### 🚛 CATEGORIA G: Tipos de Trailer

| Código | Descripción | Ejemplo |
|--------|-------------|---------|
| `TRAILER_LOWBOY` | Lowboy trailer | `TRAILER_LOWBOY` |
| `TRAILER_ENDDUMP` | End dump trailer | `TRAILER_ENDDUMP` |
| `TRAILER_SANDBOX` | Sandbox trailer | `TRAILER_SANDBOX` |
| `TRAILER_DRY_VAN` | Dry Van trailer | `TRAILER_DRY_VAN` |

### 🏭 CATEGORIA H: Condiciones Especiales

| Código | Descripción | Ejemplo |
|--------|-------------|---------|
| `ACEPTA_BOSQUE` | Acepta ir al bosque | `ACEPTA_BOSQUE` |
| `ACEPTA_VERTEDERO` | Acepta vertedero | `ACEPTA_VERTEDERO` |
| `OWNER_MIN_30_YEARS` | Dueño mínimo 30 años | `OWNER_MIN_30_YEARS` |
| `INDUSTRY_EXP_3+` | Experiencia en industria 3+ años | `INDUSTRY_EXP_3+` |
| `LICENSE_TX_REQUIRED` | Licencia de TX requerida | `LICENSE_TX_REQUIRED` |
| `CONTRATO_REQUIRED` | Contrato requerido | `CONTRATO_REQUIRED` |
| `SIN_RAMPA` | Sin rampa | `SIN_RAMPA` |

### 🏢 CATEGORIA I: Compañías Específicas

| Código | Descripción | Ejemplo |
|--------|-------------|---------|
| `COMPANY_CANAL` | Canal Insurance | `COMPANY_CANAL` |
| `COMPANY_BULLDOG` | Bulldog Insurance | `COMPANY_BULLDOG` |
| `COMPANY_ONE80` | One80 Insurance | `COMPANY_ONE80` |
| `TEST_DRIVE` | Test drive disponible | `TEST_DRIVE` |
| `CONDADOS_PROHIBIDOS` | Restricción de condados | `CONDADOS_PROHIBIDOS` |

### ❓ CATEGORIA J: Reglas Personalizadas

| Código | Descripción | Ejemplo |
|--------|-------------|---------|
| `CUSTOM_RULE` | Regla personalizada que requiere revisión manual | `CUSTOM_RULE` |

---

## Ejemplos de Uso

### Ejemplo 1: Regla Simple
**COMENTARIO**: `3+ años en el negocio`  
**CÓDIGO**: `BUSINESS_YEARS_3+`

### Ejemplo 2: Regla Compuesta
**COMENTARIO**: `CDL con 2 años de experiencia demostrable, MVR, pérdidas (Si aplica).`  
**CÓDIGO**: `CDL_YEARS_2|MVR|PERDIDAS_SI_APLICA`

### Ejemplo 3: Regla Compleja
**COMENTARIO**: `Down del 25%, precios empiezan sobre $25K, registraciones, MVR,CDL e IFTAS (Si aplica).`  
**CÓDIGO**: `DOWN_25%|MIN_PRICE_25K|REGISTRACIONES|MVR|CDL_YEARS_2|IFTAS_SI_APLICA`

### Ejemplo 4: Regla con Restricciones
**COMENTARIO**: `Solo con NICO, MVR, CDL con 2 años de experiencia demostrable, pérdidas (Si aplica).`  
**CÓDIGO**: `SOLO_NICO|MVR|CDL_YEARS_2|PERDIDAS_SI_APLICA`

---

## Notas Importantes

1. **Separador**: Las reglas múltiples se separan con el carácter `|` (pipe)
2. **Orden**: No hay un orden específico requerido para los códigos
3. **Vacíos**: Si el comentario original está vacío o es `-`, la regla estandarizada estará vacía
4. **Extensibilidad**: Este catálogo puede expandirse agregando nuevos códigos según sea necesario

---

## Uso en Automatización

Para parsear las reglas en tu proceso de automatización:

```python
# Python
regla = "CDL_YEARS_2|MVR|PERDIDAS_SI_APLICA"
codigos = regla.split('|')
# codigos = ['CDL_YEARS_2', 'MVR', 'PERDIDAS_SI_APLICA']

# Verificar si una regla específica existe
if 'CDL_YEARS_2' in codigos:
    print("Requiere CDL de 2 años")
```

```javascript
// JavaScript
const regla = "CDL_YEARS_2|MVR|PERDIDAS_SI_APLICA";
const codigos = regla.split('|');
// codigos = ['CDL_YEARS_2', 'MVR', 'PERDIDAS_SI_APLICA']

// Verificar si una regla específica existe
if (codigos.includes('CDL_YEARS_2')) {
    console.log("Requiere CDL de 2 años");
}
```
