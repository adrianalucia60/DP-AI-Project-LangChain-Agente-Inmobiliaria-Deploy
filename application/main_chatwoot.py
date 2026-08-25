"""
Integración del Agente IA con Chatwoot
Webhook para recibir mensajes y responder automáticamente.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import sys
import uuid
import logging
import requests
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, Request
import uvicorn

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("alpha_state.chatwoot")

# Cargar variables de entorno
load_dotenv(find_dotenv())

# Agregar el directorio actual al path (portable para despliegue)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ✅ LAZY LOAD: No importar el agente aquí, hacerlo después
chat_con_agente = None
tools = []

logger.info("Inicializando aplicación; carga del agente diferida")

# ============================================
# CONFIGURACIÓN DE CHATWOOT
# ============================================
CHATWOOT_BASE_URL = os.getenv("CHATWOOT_BASE_URL")
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_ACCESS_TOKEN")

# Etiqueta que activa el bot (opcional, para handoff)
BOT_LABEL = os.getenv("CHATWOOT_BOT_LABEL", "atiende-ia")
# Etiqueta que desactiva la IA: si el usuario/conversación tiene "ia-off", el agente NO responde
TAG_IA_OFF = "ia-off"

if not all([CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_TOKEN]):
    logger.warning(
        "Faltan variables de Chatwoot; requeridas: "
        "CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_ACCESS_TOKEN"
    )
else:
    logger.info("Chatwoot configurado en %s", CHATWOOT_BASE_URL)

# ============================================
# FUNCIONES DE CHATWOOT
# ============================================
def send_chatwoot_message(conversation_id: int, message: str) -> bool:
    """
    Envía un mensaje de respuesta a una conversación en Chatwoot.
    
    Args:
        conversation_id: ID de la conversación
        message: Mensaje a enviar
    
    Returns:
        True si se envió correctamente, False si hubo error
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
    headers = {
        'api_access_token': CHATWOOT_API_TOKEN,
        'Content-Type': 'application/json'
    }
    payload = {
        'content': message,
        'message_type': 'outgoing'
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info("Mensaje enviado a conversación %s", conversation_id)
        return True
    except requests.exceptions.RequestException as e:
        logger.exception("Error al enviar mensaje a conversación %s", conversation_id)
        return False


def update_chatwoot_labels(conversation_id: int, labels: list) -> bool:
    """
    Actualiza las etiquetas de una conversación en Chatwoot.
    
    Args:
        conversation_id: ID de la conversación
        labels: Lista de etiquetas
    
    Returns:
        True si se actualizó correctamente
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/labels"
    headers = {
        'api_access_token': CHATWOOT_API_TOKEN,
        'Content-Type': 'application/json'
    }
    payload = {'labels': labels}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info("Etiquetas actualizadas en conversación %s", conversation_id)
        return True
    except requests.exceptions.RequestException as e:
        logger.exception("Error al actualizar etiquetas en conversación %s", conversation_id)
        return False


def conversation_id_to_uuid(conversation_id: int) -> str:
    """
    Convierte un conversation_id de Chatwoot a un UUID válido.
    Esto permite usar el mismo session_id para la misma conversación.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"chatwoot-{conversation_id}"))

def load_agent():
    """Carga el agente de forma lazy (solo cuando se necesita)."""
    global chat_con_agente, tools
    if chat_con_agente is None:
        logger.info("Cargando agente Alpha State y sus dependencias")
        try:
            from agent import chat_con_agente as _chat, tools as _tools
            chat_con_agente = _chat
            tools = _tools
            logger.info("Agente cargado correctamente; herramientas=%s", len(tools))
        except Exception:
            logger.exception("No se pudo cargar el agente")
            raise

# ============================================
# FASTAPI APP
# ============================================
app = FastAPI(
    title="Alpha State - Agente IA con Chatwoot",
    description="Webhook para integrar el agente de Alpha State con Chatwoot",
    version="1.0.0"
)


@app.post("/webhook")
async def chatwoot_webhook(request: Request):
    """
    Endpoint que recibe los webhooks de Chatwoot.
    Procesa mensajes entrantes y responde usando el agente de Alpha State.
    """
    data = await request.json()
    
    # Extraer información del webhook
    event = data.get('event')
    message_type = data.get('message_type')
    conversation = data.get('conversation', {})
    labels = conversation.get('labels', [])
    message_content = data.get('content')
    conversation_id = conversation.get('id')
    sender = data.get('sender', {})
    sender_type = sender.get('type', '')
    
    # Debug
    logger.info(
        "Webhook recibido: event=%s conversation_id=%s message_type=%s labels=%s",
        event,
        conversation_id,
        message_type,
        labels,
    )
    
    # Solo procesar mensajes entrantes (del usuario, no del bot)
    if event != 'message_created':
        return {"status": "ignored", "reason": "Not a message_created event"}
    
    if message_type != 'incoming':
        return {"status": "ignored", "reason": "Not an incoming message"}
    
    # No responder si el usuario/conversación tiene el tag "ia-off"
    if TAG_IA_OFF in labels:
        logger.info("Webhook ignorado: etiqueta '%s'", TAG_IA_OFF)
        return {"status": "ignored", "reason": f"User has tag '{TAG_IA_OFF}'"}
    
    if not message_content or not conversation_id:
        return {"status": "ignored", "reason": "Missing content or conversation_id"}
    
    logger.info("Mensaje recibido: caracteres=%s", len(message_content))
    
    # Detectar si el usuario quiere hablar con un humano
    human_keywords = ['humano', 'persona', 'asesor', 'agente', 'representante', 'hablar con alguien']
    if any(keyword in message_content.lower() for keyword in human_keywords):
        logger.info("Transferencia a humano detectada: conversation_id=%s", conversation_id)
        
        # Actualizar etiquetas
        new_labels = [l for l in labels if l != BOT_LABEL]
        new_labels.append('atiende-humano')
        update_chatwoot_labels(conversation_id, new_labels)
        
        # Mensaje de despedida
        handoff_message = "Entendido. Un asesor humano se pondrá en contacto contigo en breve. ¡Gracias por tu paciencia!"
        send_chatwoot_message(conversation_id, handoff_message)
        
        return {"status": "success", "action": "human_handoff"}
    
    # Procesar con el agente
    try:
        logger.info("Procesando conversación %s con el agente", conversation_id)
        load_agent()
        
        # Convertir conversation_id a UUID para el historial
        session_id = conversation_id_to_uuid(conversation_id)
        logger.info("Historial seleccionado para conversación %s", conversation_id)
        
        # Llamar al agente
        respuesta = chat_con_agente(message_content, session_id)
        
        logger.info("Respuesta generada: caracteres=%s", len(respuesta))
        
        # Enviar respuesta a Chatwoot
        send_chatwoot_message(conversation_id, respuesta)
        
        return {"status": "success", "action": "agent_response"}
        
    except Exception as e:
        logger.exception("Error al procesar conversación %s", conversation_id)

        # Enviar mensaje de error
        error_message = "Disculpa, tuve un problema al procesar tu consulta. Un asesor te atenderá pronto."
        send_chatwoot_message(conversation_id, error_message)
        
        return {"status": "error", "message": str(e)}


@app.get("/")
def read_root():
    """Endpoint raíz con información del servicio."""
    return {
        "service": "Alpha State - Agente IA",
        "version": "1.0.0",
        "agent": "Alpha State (Sheets + RAG + Internet + Memoria)",
        "model": "GPT-4.1",
        "tools": [t.name for t in tools],
        "chatwoot_configured": all([CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_TOKEN]),
        "agent_loaded": chat_con_agente is not None,
        "bot_label": BOT_LABEL,
        "status": "ready"
    }


@app.get("/health")
def health_check():
    """Endpoint de salud del servicio."""
    return {
        "status": "healthy",
        "agent": "Alpha State",
        "agent_loaded": chat_con_agente is not None,
        "chatwoot": "connected" if all([CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_TOKEN]) else "not configured"
    }


@app.post("/test")
async def test_agent(request: Request):
    """
    Endpoint de prueba para testear el agente sin Chatwoot.
    
    Body: {"message": "tu pregunta", "session_id": "opcional"}
    """
    data = await request.json()
    message = data.get('message', '')
    session_id = data.get('session_id', str(uuid.uuid4()))
    
    if not message:
        return {"error": "Debes proporcionar un 'message' en el body"}
    
    logger.info("Solicitud /test recibida: caracteres=%s", len(message))
    
    try:
        load_agent()
        respuesta = chat_con_agente(message, session_id)
        logger.info("/test completado: caracteres_respuesta=%s", len(respuesta))
        
        return {
            "message": message,
            "session_id": session_id,
            "response": respuesta,
            "status": "success"
        }
    except Exception as e:
        logger.exception("Error en /test")
        return {
            "message": message,
            "error": str(e),
            "status": "error"
        }


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print()
    print("=" * 60)
    print("🚀 INICIANDO DATABOT CON CHATWOOT")
    print("=" * 60)
    print(f"🤖 Agente: Alpha State (Sheets + RAG + Internet + Memoria)")
    print(f"🧠 Modelo: GPT-4.1")
    print(f"🔧 Tools: {', '.join(t.name for t in tools)}")
    print(f"💾 Historial: PostgreSQL")
    print(f"🏷️  Etiqueta bot (handoff): {BOT_LABEL or 'ninguna'}")
    print(f"🚫 No responde si tiene tag: {TAG_IA_OFF}")
    print("=" * 60)
    print()
    
    uvicorn.run(app, host="0.0.0.0", port=8080)
