# OpenAI Local Proxy — Manual de uso del API

Este documento explica cómo hacer peticiones al proxy local y cómo integrarlo en tus aplicaciones.

**Base URL:** `http://localhost:3000`

---

## Tabla de contenidos

1. [Arrancar el servidor](#arrancar-el-servidor)
2. [Endpoints disponibles](#endpoints-disponibles)
3. [POST /v1/chat/completions](#post-v1chatcompletions)
4. [Casos de uso prácticos](#casos-de-uso-prácticos)
5. [Integración con código](#integración-con-código)
6. [Modelos disponibles](#modelos-disponibles)
7. [Errores comunes](#errores-comunes)

---

## Arrancar el servidor

Antes de hacer cualquier petición, el servidor debe estar corriendo:

```bash
cd C:\Users\Desarrollo\Documents\AgentAI
npm start
```

Espera a ver este mensaje en la terminal:

```
✓ Proxy corriendo en http://localhost:3000
  Modelo por defecto: openai/gpt-5.4
```

A partir de ese momento el proxy está listo para recibir peticiones.

---

## Endpoints disponibles

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/health` | Verifica que el proxy y OpenCode están activos |
| `GET` | `/v1/models` | Lista los modelos disponibles |
| `POST` | `/v1/chat/completions` | Envía un mensaje y obtiene respuesta |

---

## GET /health

Verifica el estado del sistema.

### Request

```bash
curl http://localhost:3000/health
```

### Response

```json
{
  "status": "ok",
  "proxy": "running",
  "opencode": "connected",
  "default_model": "openai/gpt-5.4"
}
```

| Campo | Valores posibles | Significado |
|---|---|---|
| `proxy` | `running` | El proxy HTTP está activo |
| `opencode` | `connected` / `unreachable` | Si OpenCode responde correctamente |
| `default_model` | string | El modelo que se usará si no especificas uno |

---

## GET /v1/models

Lista de modelos disponibles en formato compatible con OpenAI.

### Request

```bash
curl http://localhost:3000/v1/models
```

### Response

```json
{
  "object": "list",
  "data": [
    { "id": "gpt-4o", "object": "model", "owned_by": "openai" },
    { "id": "gpt-4o-mini", "object": "model", "owned_by": "openai" }
  ]
}
```

> Los modelos reales usados son GPT-5 (por tu cuenta Pro). Los IDs `gpt-4o` y `gpt-4o-mini` se listan por compatibilidad con apps existentes, y se redirigen automáticamente al modelo default.

---

## POST /v1/chat/completions

El endpoint principal. Acepta el mismo formato que la API oficial de OpenAI.

### Headers requeridos

```
Content-Type: application/json
```

Si configuraste `API_SECRET` en `.env`:

```
Authorization: Bearer <tu_token_secreto>
```

### Body

```json
{
  "model": "gpt-4o",
  "messages": [
    { "role": "system", "content": "Instrucciones de comportamiento" },
    { "role": "user", "content": "El mensaje del usuario" }
  ]
}
```

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `messages` | array | **Sí** | Array de mensajes. Mínimo uno con `role: "user"` |
| `model` | string | No | Modelo a usar. Si se omite, usa el default detectado |
| `stream` | boolean | No | Solo acepta `false`. El streaming no está soportado |
| `temperature` | number | No | Se recibe pero no afecta el comportamiento (OpenCode lo gestiona) |
| `max_tokens` | number | No | Se recibe pero no afecta el comportamiento |

### Enviar imagenes (vision)

El endpoint acepta imagenes en formato base64 usando el mismo formato que la API oficial de OpenAI. Para enviar una imagen, el campo `content` del mensaje se convierte en un array de partes:

```json
{
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "¿Qué ves en esta imagen?" },
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg..."
          }
        }
      ]
    }
  ]
}
```

| Campo | Descripcion |
|---|---|
| `content` | Puede ser `string` (solo texto) o un array de partes (texto + imagenes) |
| `type: "text"` | Parte de texto del mensaje |
| `type: "image_url"` | Parte de imagen. El campo `url` debe ser un data URL base64 |

**Restricciones:**

- **Solo base64 data URLs.** URLs remotas (`https://...`) son ignoradas. La imagen debe estar codificada inline como `data:image/<formato>;base64,...`
- **Formatos soportados:** PNG, JPEG, GIF, WebP
- **Limite de tamaño:** 10 MB total del body (incluyendo la imagen codificada en base64)
- El campo `detail` de `image_url` se acepta pero se ignora

**Ejemplo con curl:**

```bash
# Codificar una imagen a base64 y enviarla
BASE64_IMG=$(base64 -w 0 mi_imagen.png)

curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{
    \"messages\": [
      {
        \"role\": \"user\",
        \"content\": [
          { \"type\": \"text\", \"text\": \"Describe esta imagen en español\" },
          {
            \"type\": \"image_url\",
            \"image_url\": {
              \"url\": \"data:image/png;base64,${BASE64_IMG}\"
            }
          }
        ]
      }
    ]
  }"
```

**Ejemplo con el SDK de OpenAI (Node.js):**

```javascript
import OpenAI from "openai";
import fs from "fs";

const openai = new OpenAI({
  apiKey: "no-se-usa",
  baseURL: "http://localhost:3000/v1"
});

// Leer imagen y convertir a base64
const imageBuffer = fs.readFileSync("mi_imagen.png");
const base64Image = imageBuffer.toString("base64");
const dataUrl = `data:image/png;base64,${base64Image}`;

const response = await openai.chat.completions.create({
  model: "gpt-4o",
  messages: [
    {
      role: "user",
      content: [
        { type: "text", text: "¿Qué ves en esta imagen?" },
        { type: "image_url", image_url: { url: dataUrl } }
      ]
    }
  ]
});

console.log(response.choices[0].message.content);
```

**Ejemplo con el SDK de OpenAI (Python):**

```python
from openai import OpenAI
import base64

client = OpenAI(
    api_key="no-se-usa",
    base_url="http://localhost:3000/v1"
)

# Leer imagen y convertir a base64
with open("mi_imagen.png", "rb") as f:
    base64_image = base64.b64encode(f.read()).decode("utf-8")

data_url = f"data:image/png;base64,{base64_image}"

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "¿Qué ves en esta imagen?"},
                {"type": "image_url", "image_url": {"url": data_url}}
            ]
        }
    ]
)

print(response.choices[0].message.content)
```

> **Nota:** Puedes combinar texto e imagenes libremente. Tambien puedes enviar mensajes con solo texto (string) y otros con imagenes (array) en la misma conversacion. La retrocompatibilidad con `content: "texto"` se mantiene.

### Roles de mensajes

| Rol | Descripción |
|---|---|
| `system` | Instrucciones de comportamiento para el modelo. Va primero si se incluye |
| `user` | El mensaje del usuario / el prompt |
| `assistant` | Respuestas previas del modelo (para conversaciones multi-turno) |

### Response

```json
{
  "id": "chatcmpl-44e1943b-f8f9-46c9-bf36-02b6106bde6a",
  "object": "chat.completion",
  "created": 1772829800,
  "model": "gpt-5.4",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "La respuesta del modelo aquí"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 45,
    "completion_tokens": 23,
    "total_tokens": 68
  }
}
```

La respuesta del modelo siempre está en `choices[0].message.content`.

---

## Casos de uso prácticos

### 1. Pregunta simple

El caso más básico: una pregunta directa.

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      { "role": "user", "content": "¿Cuánto es 15 por 47?" }
    ]
  }'
```

---

### 2. Extraer datos de un correo y devolver JSON

Usa un `system` prompt para instruir al modelo que responda solo con JSON.

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "system",
        "content": "Eres un extractor de datos. Responde ÚNICAMENTE con JSON válido, sin texto adicional, sin bloques de código."
      },
      {
        "role": "user",
        "content": "Extrae los datos de este correo y devuélveme un JSON con los campos: remitente, asunto, fecha, resumen (máximo 2 oraciones).\n\nCorreo:\nDe: carlos@empresa.com\nAsunto: Reunión de planificación Q3\nFecha: 5 de marzo de 2026\n\nHola equipo, les recuerdo que tenemos reunión de planificación del Q3 el próximo lunes a las 10am en la sala de conferencias principal. Por favor confirmen asistencia antes del viernes."
      }
    ]
  }'
```

**Respuesta esperada:**

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "{\"remitente\":\"carlos@empresa.com\",\"asunto\":\"Reunión de planificación Q3\",\"fecha\":\"5 de marzo de 2026\",\"resumen\":\"Se convoca a reunión de planificación del Q3 el próximo lunes a las 10am. Se solicita confirmación de asistencia antes del viernes.\"}"
    }
  }]
}
```

Para parsear el JSON de la respuesta directamente en bash:

```bash
curl -s -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{ "messages": [{"role":"system","content":"Responde solo con JSON"},{"role":"user","content":"Extrae: remitente, asunto de: De: ana@corp.com\nAsunto: Informe mensual"}] }' \
  | node -e "const c=[];process.stdin.on('data',d=>c.push(d));process.stdin.on('end',()=>{ const r=JSON.parse(Buffer.concat(c).toString()); console.log(JSON.parse(r.choices[0].message.content)); })"
```

---

### 3. Clasificar el tono o urgencia de mensajes

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "system",
        "content": "Clasificas mensajes. Responde SOLO con JSON: {\"urgencia\": \"alta|media|baja\", \"tono\": \"formal|informal|urgente|neutro\", \"accion_requerida\": true|false}"
      },
      {
        "role": "user",
        "content": "IMPORTANTE: Necesito que me entregues el reporte de ventas HOY antes de las 5pm sin falta. El cliente está esperando."
      }
    ]
  }'
```

---

### 4. Resumir texto largo

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "system",
        "content": "Eres un asistente que resume textos de forma concisa. Máximo 3 puntos clave en español."
      },
      {
        "role": "user",
        "content": "Resume este artículo: [pega aquí el texto largo]"
      }
    ]
  }'
```

---

### 5. Traducción con instrucciones específicas

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "system",
        "content": "Traduce al inglés de forma natural y profesional. Responde solo con la traducción, sin explicaciones."
      },
      {
        "role": "user",
        "content": "La reunión fue postergada debido a inconvenientes técnicos imprevistos. Les notificaremos la nueva fecha a la brevedad."
      }
    ]
  }'
```

---

### 6. Especificar un modelo distinto

Si quieres usar un modelo específico de tu cuenta Pro:

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-5.2",
    "messages": [
      { "role": "user", "content": "Hola, ¿qué modelo eres?" }
    ]
  }'
```

---

### 7. Analizar una imagen

Enviar una imagen para que el modelo la describa o extraiga informacion:

```bash
# Codificar imagen a base64
BASE64_IMG=$(base64 -w 0 factura.jpg)

curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{
    \"messages\": [
      {
        \"role\": \"system\",
        \"content\": \"Extraes datos de facturas. Responde UNICAMENTE con JSON valido.\"
      },
      {
        \"role\": \"user\",
        \"content\": [
          { \"type\": \"text\", \"text\": \"Extrae: proveedor, monto_total, fecha, numero_factura\" },
          { \"type\": \"image_url\", \"image_url\": { \"url\": \"data:image/jpeg;base64,${BASE64_IMG}\" } }
        ]
      }
    ]
  }"
```

**Respuesta esperada:**

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "{\"proveedor\":\"Suministros ABC\",\"monto_total\":\"$1,250.00\",\"fecha\":\"2026-03-15\",\"numero_factura\":\"FAC-00847\"}"
    }
  }]
}
```

---

### 8. Con token de autenticación (si configuraste API_SECRET)

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mi_token_secreto" \
  -d '{
    "messages": [
      { "role": "user", "content": "Hola" }
    ]
  }'
```

---

## Integración con código

### JavaScript / Node.js (fetch nativo)

```javascript
async function askAI(prompt, systemPrompt = null) {
  const messages = [];
  
  if (systemPrompt) {
    messages.push({ role: "system", content: systemPrompt });
  }
  messages.push({ role: "user", content: prompt });

  const response = await fetch("http://localhost:3000/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages })
  });

  const data = await response.json();
  return data.choices[0].message.content;
}

// Uso
const resultado = await askAI(
  "Extrae los datos de este correo: De: ana@corp.com...",
  "Responde solo con JSON válido"
);
console.log(JSON.parse(resultado));
```

---

### JavaScript / Node.js (SDK oficial de OpenAI)

La SDK de OpenAI permite cambiar la `baseURL` para apuntar al proxy local. **No se necesita una API Key real** (el proxy la ignora), pero la SDK requiere que el campo exista.

```javascript
import OpenAI from "openai";

const openai = new OpenAI({
  apiKey: "no-se-usa",           // Requerido por la SDK pero ignorado por el proxy
  baseURL: "http://localhost:3000/v1"
});

const response = await openai.chat.completions.create({
  model: "gpt-4o",               // Se redirige automáticamente al modelo de tu cuenta Pro
  messages: [
    {
      role: "system",
      content: "Responde solo con JSON válido"
    },
    {
      role: "user",
      content: "Clasifica este texto: 'URGENTE: reunión en 10 minutos'"
    }
  ]
});

console.log(response.choices[0].message.content);
```

---

### Python (requests)

```python
import requests
import json

def ask_ai(prompt: str, system_prompt: str = None) -> str:
    messages = []
    
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    response = requests.post(
        "http://localhost:3000/v1/chat/completions",
        headers={"Content-Type": "application/json"},
        json={"messages": messages}
    )
    
    data = response.json()
    return data["choices"][0]["message"]["content"]


# Ejemplo: extraer datos de un correo
correo = """
De: proveedor@logistica.com
Asunto: Actualización de envío #4521
Fecha: 6 de marzo de 2026

Su pedido ha sido despachado. Número de seguimiento: TRK-887234.
Entrega estimada: 8 de marzo entre 9am y 6pm.
"""

resultado = ask_ai(
    prompt=f"Extrae los datos de este correo:\n{correo}",
    system_prompt="Responde ÚNICAMENTE con JSON. Campos: remitente, asunto, numero_seguimiento, fecha_entrega"
)

datos = json.loads(resultado)
print(datos)
# {"remitente": "proveedor@logistica.com", "asunto": "...", ...}
```

---

### Python (SDK oficial de OpenAI)

```python
from openai import OpenAI

client = OpenAI(
    api_key="no-se-usa",                          # Requerido por la SDK, ignorado por el proxy
    base_url="http://localhost:3000/v1"
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "Responde en JSON"},
        {"role": "user", "content": "Clasifica: 'Entrega retrasada 3 días'"}
    ]
)

print(response.choices[0].message.content)
```

---

### Ejemplo completo: procesador de correos

```javascript
// emailProcessor.js
import fetch from "node-fetch"; // o fetch nativo en Node 18+

const PROXY_URL = "http://localhost:3000/v1/chat/completions";

const SYSTEM_PROMPT = `
Eres un extractor de datos de correos electrónicos.
Analiza el correo proporcionado y devuelve ÚNICAMENTE un JSON válido con esta estructura exacta:
{
  "remitente": "email del remitente",
  "nombre_remitente": "nombre si aparece, null si no",
  "asunto": "asunto del correo",
  "fecha": "fecha en formato YYYY-MM-DD si aparece, null si no",
  "prioridad": "alta | media | baja",
  "requiere_respuesta": true o false,
  "resumen": "resumen en máximo 2 oraciones",
  "accion_sugerida": "qué hacer con este correo"
}
`.trim();

async function procesarCorreo(contenidoCorreo) {
  const response = await fetch(PROXY_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: contenidoCorreo }
      ]
    })
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(`Error del proxy: ${error.error?.message}`);
  }

  const data = await response.json();
  const contenidoRespuesta = data.choices[0].message.content;

  // El modelo debería devolver JSON puro, pero limpiamos por si acaso
  const jsonLimpio = contenidoRespuesta
    .replace(/```json\n?/g, "")
    .replace(/```\n?/g, "")
    .trim();

  return JSON.parse(jsonLimpio);
}

// Uso
const correoEjemplo = `
De: Maria Garcia <mgarcia@proveedor.com>
Para: jrodriguez@empresa.com
Asunto: Re: Cotización proyecto #2234 - URGENTE necesitamos respuesta
Fecha: Viernes, 6 de marzo de 2026

Hola Juan,

Necesitamos tu confirmación para la cotización del proyecto #2234 antes del lunes.
Tenemos otro cliente interesado y no podemos mantener la propuesta más tiempo.

Quedo en espera de tu respuesta urgente.

Saludos,
María García
Gerente Comercial
`;

procesarCorreo(correoEjemplo)
  .then(datos => {
    console.log("Datos extraídos:");
    console.log(JSON.stringify(datos, null, 2));
  })
  .catch(err => console.error("Error:", err.message));
```

**Salida esperada:**

```json
{
  "remitente": "mgarcia@proveedor.com",
  "nombre_remitente": "Maria Garcia",
  "asunto": "Re: Cotización proyecto #2234 - URGENTE necesitamos respuesta",
  "fecha": "2026-03-06",
  "prioridad": "alta",
  "requiere_respuesta": true,
  "resumen": "María García solicita confirmación urgente para cotización del proyecto #2234 antes del lunes. Otra empresa está interesada, por lo que la propuesta tiene fecha límite.",
  "accion_sugerida": "Responder hoy o mañana con decisión sobre la cotización #2234"
}
```

---

## Modelos disponibles

Con tu cuenta **ChatGPT Pro**, los modelos disponibles son la serie GPT-5:

| ID para usar en el proxy | Descripción |
|---|---|
| `openai/gpt-5.4` | El más reciente y capaz. **Default auto-detectado** |
| `openai/gpt-5.2` | Versión anterior, también muy capaz |
| `openai/gpt-5.1-codex` | Optimizado para generación de código |
| `openai/gpt-5.2-codex` | Codex más reciente |
| `openai/codex-mini-latest` | Versión ligera, respuestas más rápidas |

### Cómo especificar el modelo

**Opción A — Dejar que el proxy elija (recomendado):**

No incluyas el campo `model` o usa cualquier nombre estándar (`gpt-4o`, `gpt-4o-mini`, etc.):

```json
{ "messages": [...] }
```

El proxy usa automáticamente `openai/gpt-5.4`.

**Opción B — Especificar modelo explícitamente:**

Usa el formato `proveedor/modelo`:

```json
{
  "model": "openai/gpt-5.2",
  "messages": [...]
}
```

---

## Errores comunes

### HTTP 400 — Bad Request

```json
{
  "error": {
    "message": "El campo 'messages' es requerido y debe ser un array",
    "type": "invalid_request_error"
  }
}
```

**Causa:** Falta el campo `messages` o no es un array.

**Solución:** Asegúrate de enviar:
```json
{ "messages": [{ "role": "user", "content": "..." }] }
```

---

```json
{
  "error": {
    "message": "Streaming no soportado en esta versión.",
    "type": "invalid_request_error"
  }
}
```

**Causa:** Enviaste `"stream": true`.

**Solución:** Elimina `stream` del body o usa `"stream": false`.

---

### HTTP 401 — Unauthorized

```json
{ "error": "Unauthorized: invalid token" }
```

**Causa:** Configuraste `API_SECRET` en `.env` pero no enviaste el header de autenticación, o el token es incorrecto.

**Solución:** Incluye en el request:
```
Authorization: Bearer <tu_token_configurado_en_env>
```

---

### HTTP 503 — Service Unavailable

```json
{
  "error": {
    "message": "OpenCode server no está disponible.",
    "type": "server_error"
  }
}
```

**Causa:** El proceso `opencode serve` se cayó o no responde.

**Solución:** Reinicia el proxy completo con `npm start`. Si el problema persiste, verifica que tienes conexión a internet y que tu sesión de ChatGPT Pro está activa.

---

### HTTP 500 — Internal Server Error

```json
{
  "error": {
    "message": "Request failed with status code 400",
    "type": "server_error"
  }
}
```

**Causa más común:** El modelo especificado no existe en tu cuenta.

**Solución:** Usa `DEFAULT_MODEL=` vacío en `.env` para auto-detección, o usa uno de los modelos listados en la tabla de [Modelos disponibles](#modelos-disponibles).

---

## Notas importantes

- **Stateless por diseño:** Cada petición crea y elimina su propia sesión de OpenCode. No hay memoria entre peticiones. Si necesitas conversaciones multi-turno, incluye todo el historial en el array `messages`.
- **Sin streaming:** Las respuestas se reciben de forma completa. Para textos muy largos, la petición puede tardar hasta 2 minutos (timeout configurado).
- **Tokens estimados:** El campo `usage` en la respuesta es una estimación (1 token ≈ 4 caracteres). No refleja el conteo real de tokens de OpenAI.
- **Límite de body:** El servidor acepta hasta 10 MB por petición. Para textos muy largos, considera dividirlos en chunks. Para imágenes, ten en cuenta que base64 agrega ~33% al tamaño original (una imagen de 6 MB ocupa ~8 MB en base64).
- **Soporte de imágenes:** El endpoint acepta imágenes base64 en el formato estándar de OpenAI (`content` como array con partes `text` e `image_url`). Solo se aceptan data URLs base64, no URLs remotas. Formatos: PNG, JPEG, GIF, WebP.
