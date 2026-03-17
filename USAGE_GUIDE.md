# Guía de Contexto: ¿Cómo utilizar OpenAI Local Proxy en otros proyectos?

Esta guía explica conceptualmente cómo funciona el "OpenAI Local Proxy" y cómo puedes conectar otros proyectos (scripts, backends, automatizaciones, n8n, etc.) a él para utilizar la IA (ChatGPT Pro).

## ¿Qué es y cómo funciona el Proxy?

Piensa en este proxy como un **"traductor y puente"**.

1. **Tu Cuenta:** Tienes una cuenta de ChatGPT Plus/Pro.
2. **OpenCode CLI:** Es una herramienta que se conecta a tu cuenta de ChatGPT usando cookies y simula ser la aplicación oficial, creando un servidor interno (opencode serve).
3. **OpenAI Local Proxy:** Es el servicio que acabamos de crear. Su trabajo es disfrazarse de la API oficial de OpenAI (`https://api.openai.com/...`) pero localmente.

### El Flujo

`Tu Nuevo Proyecto` ➡️(envía JSON estilo OpenAI)➡️ `OpenAI Local Proxy (localhost:3000)` ➡️ `OpenCode` ➡️ `ChatGPT Pro`

### ¿Por qué es útil?

Cualquier librería, SDK o herramienta que ya sepa cómo hablar con la API oficial de OpenAI (como LangChain, las librerías `openai` de Python o Node.js, n8n, AutoGen, etc.) **funcionará automáticamente** con este proxy. Solo necesitas decirle a esas herramientas que NO se conecten a internet (`api.openai.com`), sino que se conecten a tu servidor local (`localhost:3000/v1`).

---

## Cómo usar el servicio en otros Proyectos

La regla de oro es: **Utiliza las librerías oficiales de OpenAI como si estuvieras pagando la API oficial, pero cambia la "Base URL".**

### Ejemplo 1: Desde un script en Python (Usando la librería oficial de OpenAI)

Si estás haciendo un script en Python para procesar datos, no necesitas hacer `requests.post` manualmente. Usa la librería de OpenAI.

```python
# pip install openai
from openai import OpenAI

# 1. Configuras el cliente para apuntar a tu proxy local
client = OpenAI(
    base_url="http://localhost:3000/v1",
    api_key="si_pusiste_api_secret_ponlo_aqui_sino_cualquier_texto_sirve" # Ej. "sk-local"
)

# 2. Úsalo como lo usarías normalmente
response = client.chat.completions.create(
    model="gpt-5.4", # El proxy lo ignorará y usará el default, pero la librería lo requiere
    messages=[
        {"role": "system", "content": "Eres un asistente experto en Python."},
        {"role": "user", "content": "¿Cómo hago un for loop?"}
    ]
)

print(response.choices[0].message.content)
```

### Ejemplo 2: Desde un backend Node.js / TypeScript

Si estás creando otro servidor web (por ejemplo, en Express o NestJS) que necesita usar IA.

```javascript
// npm install openai
import OpenAI from "openai";

const openai = new OpenAI({
  baseURL: "http://localhost:3000/v1",
  apiKey: "sk-local", // O tu API_SECRET de .env
});

async function consultarIA(pregunta) {
  const completion = await openai.chat.completions.create({
    model: "gpt-5.4",
    messages: [
      { role: "user", content: pregunta }
    ],
  });
  
  return completion.choices[0].message.content;
}
```

### Ejemplo 3: Integración en n8n (Herramienta de automatización sin código)

Si estás construyendo flujos automáticos en n8n:

1. Agrega el nodo **OpenAI**.
2. Al crear la credencial, busca la opción que dice **"Connect using: Custom API Environment"** (o cambia la URL base si está disponible).
3. URL Base: `http://localhost:3000/v1`
4. API Key: `sk-local` (o la que hayas configurado en `.env`).
5. ¡Listo! n8n pensará que está hablando con OpenAI, pero los mensajes se irán por tu proxy usando tu suscripción de ChatGPT Pro.

---

## 3 Puntos Clave a recordar para futuros proyectos

1. **Es *Stateless* (Sin Estado):** El proxy no recuerda lo que hablaste en la petición anterior. Si quieres tener una conversación larga donde la IA recuerde el contexto, **tu nuevo proyecto** debe guardar el historial de mensajes y enviarle todo el arreglo de `messages` desde el inicio cada vez.
2. **Caídas y Alertas:** Si tu sesión caduca (suele pasar cada pocos días en OpenCode), tu nuevo proyecto recibirá un error `HTTP 503`. Tu proyecto no tiene que preocuparse por eso, porque el proxy en segundo plano **ya te habrá enviado un correo a programacion@h2oins.com** avisándote que debes re-autenticar (corriendo `/connect` en OpenCode).
3. **No soporta Streaming:** Las librerías suelen tener una opción `stream: true` (para ver a la IA escribir letra por letra). Este proxy **no soporta eso**. Siempre debes usar `stream: false` y esperar a que responda el bloque de texto completo.
