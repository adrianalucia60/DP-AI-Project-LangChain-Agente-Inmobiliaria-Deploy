# Despliegue — Agente IA Alpha State Assessoria Imobiliária

Envoltorio de despliegue del proyecto
[`Proyecto-LangChain-Inmobiliaria-Google-Sheets-2026`](../Proyecto-LangChain-Inmobiliaria-Google-Sheets-2026).

El agente completo vive en `application/` **con la misma estructura modular que el
proyecto original**: nada se aplanó ni se fusionó al traerlo acá. Lo que agrega esta
carpeta es solo la cáscara de despliegue: Dockerfiles, manifiestos de Cloud Run y el
`requirements.txt` en la raíz.

El servicio que se expone es el **webhook de Chatwoot** (`main_chatwoot.py`).

---

## Estructura

```
.
├── application/                    # 👈 EL PROYECTO (espejo del repo original)
│   ├── agent.py                    #   Orquestador: LLM + tools + prompt + memoria
│   ├── main_chatwoot.py            #   Entrypoint FastAPI: webhook de Chatwoot
│   ├── vector_store.py             #   FUENTE ÚNICA del par (embedding, colección)
│   │
│   ├── model_config/               #   Proveedor, modelo y temperatura del LLM
│   ├── prompt/                     #   System prompt (YAML + tags XML)
│   ├── tools/                      #   Una tool por archivo
│   ├── conversation_history/       #   Histórico por session_id en PostgreSQL
│   │
│   ├── credentials/                #   JSON de la cuenta de servicio de Google
│   ├── RAG-Clasico-con-Qdrant/     #   Ingesta del RAG (offline, fuera de la imagen)
│   ├── .env                        #   Secretos reales (NO se versiona)
│   └── .env.example                #   Plantilla de variables
│
├── requirements.txt                # Dependencias (en la raíz: lo pide Dockerfile.prod)
├── Dockerfile.prod                 # Imagen de producción → uvicorn en el puerto 8080
├── Dockerfile.dev                  # Imagen del devcontainer (VS Code)
├── .dockerignore                   # Deja la ingesta y los PDFs fuera de la imagen
│
├── cloudbuild.yaml                 # Build + push a Artifact Registry
├── service.yaml                    # Servicio de Cloud Run (containerPort 8080)
├── gcr-service-policy.yaml         # Acceso público (allUsers → run.invoker)
│
├── Comandos-deploy-GCP.md          # Pasos de despliegue en Google Cloud Run
└── Comandos-deploy-DigitalOcean.md # Build multiplataforma + push a Docker Hub
```

`Dockerfile.prod` fija `PYTHONPATH=/usr/src/project/application`, así que dentro del
contenedor los imports son los mismos que en local (`from tools...`,
`from conversation_history...`). No hay que reescribir rutas para desplegar.

---

## Cómo se relaciona con el proyecto original

`application/` es una copia byte a byte del proyecto (sin `.git`, `.claude` ni
`Comandos.md`). Cuando cambies el agente en el repo original, sincroniza así:

```bash
rsync -a --delete \
  --exclude '.git' --exclude '.claude' --exclude '__pycache__' \
  --exclude '.DS_Store' --exclude 'Comandos.md' --exclude 'requirements.txt' \
  "../Proyecto-LangChain-Inmobiliaria-Google-Sheets-2026/" ./application/
```

`requirements.txt` se excluye a propósito: acá vive en la raíz porque
`Dockerfile.prod` lo copia **antes** que el código, para que la capa de dependencias
quede cacheada y no se reinstale con cada cambio del agente. Si agregas una
dependencia al proyecto, replícala también en el `requirements.txt` de esta raíz.

---

## Antes del primer despliegue

1. **`application/.env`** — con los valores reales. Usa `application/.env.example`
   como referencia: cada bloque dice qué módulo lo lee y si es requerido.
2. **`application/credentials/<cuenta>.json`** — el JSON de la cuenta de servicio de
   Google, y la hoja de cálculo compartida con ese email (basta permiso de lectura).
   La ruta se declara en `GOOGLE_APPLICATION_CREDENTIALS`, relativa a `application/`.
3. **Colección de Qdrant indexada** — la ingesta es un paso aparte, no la hace el
   contenedor:
   ```bash
   cd application/RAG-Clasico-con-Qdrant && python rag.py
   ```

> `.env` y `credentials/` **sí entran a la imagen** (así funciona `load_dotenv`
> dentro del contenedor) y por eso están fuera de `.dockerignore` a propósito.
> Es la imagen la que queda con secretos: mantén el repositorio de Artifact
> Registry privado. La alternativa más segura es pasar las variables por Cloud Run
> (`--set-env-vars` / Secret Manager) y sacar el `.env` de la imagen.

---

## Probar en local antes de subir

```bash
# Construir
docker build -f Dockerfile.prod -t agente-inmobiliaria:local .

# Levantar en el 4000 (mismo puerto que Cloud Run)
docker run --rm -p 4000:4000 agente-inmobiliaria:local

# Verificar que arrancó y que las tools cargaron
curl http://localhost:4000/health
curl http://localhost:4000/

# Probar el agente sin Chatwoot
curl -X POST http://localhost:4000/test \
  -H 'Content-Type: application/json' \
  -d '{"message": "¿Cuánto es la multa por pago atrasado?"}'
```

Si el contenedor muere al arrancar, casi siempre es una variable faltante: los
módulos de tools validan sus claves al importarse (`TAVILY_API_KEY`,
`GOOGLE_SHEET_ID`, `QDRANT_URL`) y revientan de una en vez de fallar en silencio.

---

## Endpoints del servicio

| Endpoint | Método | Para qué |
|---|---|---|
| `/webhook` | POST | Recibe los eventos de Chatwoot y responde en la conversación |
| `/test` | POST | Probar el agente sin Chatwoot: `{"message": "...", "session_id": "..."}` |
| `/health` | GET | Healthcheck |
| `/` | GET | Info del servicio y lista de tools cargadas |

Una vez desplegado, apunta el webhook de Chatwoot a `https://<url-del-servicio>/webhook`.

---

## Desplegar

- **Google Cloud Run** → `Comandos-deploy-GCP.md`
- **Docker Hub / DigitalOcean** → `Comandos-deploy-DigitalOcean.md`

En Mac con chip Apple recuerda construir para `linux/amd64` (`docker buildx build
--platform linux/amd64`) si vas a subir la imagen a mano: el build nativo sale arm64
y no corre en Cloud Run ni en un droplet x86. Con `gcloud builds submit` no aplica,
porque el build ocurre en Cloud Build.

---

Autor: **Ing. Kevin Inofuente Colque** — DataPath, Programa AI Engineer.
