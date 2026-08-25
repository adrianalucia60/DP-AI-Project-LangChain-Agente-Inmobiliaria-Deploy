"""
Tool: Consulta de inmuebles en Google Sheets (SOLO LECTURA).
Lee la hoja de departamentos de Alpha State usando una cuenta de servicio.

Expone tres tools al agente:
- consultar_tipo_inmueble: tipo del inmueble por ID o lista de tipos disponibles.
- consultar_alquiler_inmueble: alquiler mensual del inmueble por ID.
- buscar_inmuebles: búsqueda por barrio y características del inmueble.

Autor: Lic. Adriana Alvarez
"""

import os
import logging
import unicodedata
from typing import Optional

from dotenv import load_dotenv, find_dotenv
from langchain_core.tools import tool

import gspread
from google.oauth2.service_account import Credentials

load_dotenv(find_dotenv())

logger = logging.getLogger("alpha_state.google_sheets_inmuebles")

# ============================================
# CONFIGURACIÓN
# ============================================
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID2")
GOOGLE_SHEETS_WORKSHEET = os.getenv("GOOGLE_SHEETS_WORKSHEET2", "Departamentos")
GOOGLE_SHEETS_HEADER_ROW = int(os.getenv("GOOGLE_SHEETS_HEADER_ROW2", "1"))
# Fila opcional con agrupaciones por encima de los encabezados. Si una celda del
# encabezado está vacía, se utiliza el último valor no vacío de esta fila.
GOOGLE_SHEETS_GROUP_ROW = int(
    os.getenv("GOOGLE_SHEETS_GROUP_ROW2", str(max(1, GOOGLE_SHEETS_HEADER_ROW - 1)))
)
GOOGLE_APPLICATION_CREDENTIALS = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS_FILE",
    "credentials/service-account.json",
)

# Scope de SOLO LECTURA
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

if not GOOGLE_SHEET_ID:
    logger.error("Falta la variable GOOGLE_SHEET_ID2")
    raise ValueError(
        "❌ Falta variable GOOGLE_SHEET_ID en .env"
    )


# ============================================
# CLIENTE GSPREAD (lazy + cache simple)
# ============================================
_worksheet = None


def _resolve_credentials_path(path: str) -> str:
    """Si la ruta es relativa, la resuelve contra el directorio del proyecto."""
    if os.path.isabs(path):
        return path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, path)


def _get_worksheet():
    """Conecta a Google Sheets de forma lazy y devuelve el worksheet."""
    global _worksheet
    if _worksheet is not None:
        return _worksheet

    creds_path = _resolve_credentials_path(GOOGLE_APPLICATION_CREDENTIALS)
    logger.info(
        "Conectando a Google Sheets de inmuebles: worksheet=%s header_row=%s credentials_file=%s",
        GOOGLE_SHEETS_WORKSHEET,
        GOOGLE_SHEETS_HEADER_ROW,
        os.path.basename(creds_path),
    )
    if not os.path.isfile(creds_path):
        raise FileNotFoundError(
            f"No se encontró el JSON de la cuenta de servicio en '{creds_path}'. "
            f"Descárgalo desde Google Cloud y colócalo en esa ruta."
        )

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID)
    _worksheet = sheet.worksheet(GOOGLE_SHEETS_WORKSHEET)
    logger.info("Conexión a Google Sheets de inmuebles establecida: worksheet=%s", GOOGLE_SHEETS_WORKSHEET)
    return _worksheet


# ============================================
# UTILIDADES
# ============================================
def _normalize(text) -> str:
    """Normaliza texto: minúsculas, sin acentos, sin espacios extra."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def _dedup_headers(headers: list) -> list:
    """Renombra encabezados duplicados con un sufijo numérico."""
    counts = {}
    out = []
    for h in headers:
        h = (h or "").strip() or "Columna"
        if h in counts:
            counts[h] += 1
            out.append(f"{h}_{counts[h]}")
        else:
            counts[h] = 1
            out.append(h)
    return out


def _merge_headers_con_grupos(group_row: list, header_row: list) -> list:
    """Combina una fila de agrupaciones con la fila de encabezados:
    - Si el encabezado tiene valor, lo utiliza tal cual.
    - Si está vacío, utiliza el último grupo no vacío.
    """
    merged = []
    current_group = ""
    for i in range(max(len(group_row), len(header_row))):
        grp = (group_row[i].strip() if i < len(group_row) else "")
        hdr = (header_row[i].strip() if i < len(header_row) else "")
        if grp:
            current_group = grp
        merged.append(hdr or current_group or "Columna")
    return merged


def _cargar_datos():
    """Lee la hoja Departamentos y devuelve encabezados y filas de datos."""
    ws = _get_worksheet()
    all_values = ws.get_all_values()
    header_idx = GOOGLE_SHEETS_HEADER_ROW - 1
    group_idx = GOOGLE_SHEETS_GROUP_ROW - 1
    if header_idx >= len(all_values):
        raise ValueError(
            f"La hoja no tiene la fila {GOOGLE_SHEETS_HEADER_ROW} para usarla como encabezado."
        )
    header_row = all_values[header_idx]
    if 0 <= group_idx < len(all_values) and group_idx != header_idx:
        headers = _merge_headers_con_grupos(all_values[group_idx], header_row)
    else:
        headers = [(h or "").strip() or "Columna" for h in header_row]
    headers = _dedup_headers(headers)
    data_rows = [r for r in all_values[header_idx + 1:] if any(c.strip() for c in r)]
    logger.info("Datos de inmuebles cargados: columnas=%s filas=%s", len(headers), len(data_rows))
    return headers, data_rows


def _columnas_inmueble(headers: list) -> tuple:
    """Devuelve los índices de ID, tipo y alquiler mensual."""
    indices = {_normalize(header): index for index, header in enumerate(headers)}
    return (
        indices.get("id inmueble"),
        indices.get("tipo"),
        indices.get("alquiler mensual (brl)"),
    )


def _indices_caracteristicas(headers: list) -> dict:
    """Devuelve los índices de las características consultables."""
    indices = {_normalize(header): index for index, header in enumerate(headers)}
    return {
        "id": indices.get("id inmueble"),
        "tipo": indices.get("tipo"),
        "barrio": indices.get("barrio"),
        "metros": indices.get("metros cuadrados"),
        "habitaciones": indices.get("habitaciones"),
        "banos": indices.get("banos"),
        "direccion": indices.get("direccion"),
        "alquiler": indices.get("alquiler mensual (brl)"),
    }


def _buscar_fila_inmueble(rows: list, headers: list, identificador: str) -> Optional[dict]:
    """Busca una fila por el ID exacto del inmueble."""
    ident_norm = _normalize(identificador)
    if not ident_norm:
        return None

    idx_identificador, _, _ = _columnas_inmueble(headers)
    if idx_identificador is None:
        return None

    for row in rows:
        if idx_identificador < len(row) and _normalize(row[idx_identificador]) == ident_norm:
            return dict(zip(headers, row))

    return None


def _listar_tipos_inmueble(rows: list, headers: list) -> list[str]:
    """Devuelve los tipos distintos registrados, preservando su orden."""
    _, idx_tipo, _ = _columnas_inmueble(headers)
    if idx_tipo is None:
        return []

    tipos = []
    vistos = set()
    for row in rows:
        if idx_tipo >= len(row):
            continue
        tipo = str(row[idx_tipo]).strip()
        tipo_norm = _normalize(tipo)
        if tipo and tipo_norm not in vistos:
            vistos.add(tipo_norm)
            tipos.append(tipo)
    return tipos


def _buscar_inmuebles_por_filtros(
    rows: list,
    headers: list,
    barrio: str = "",
    metros_cuadrados: str = "",
    habitaciones: str = "",
    banos: str = "",
) -> list[dict]:
    """Filtra inmuebles por barrio y características numéricas exactas."""
    indices = _indices_caracteristicas(headers)
    filtros_texto = {
        "barrio": _normalize(barrio),
        "metros": _normalize(metros_cuadrados),
        "habitaciones": _normalize(habitaciones),
        "banos": _normalize(banos),
    }
    resultados = []

    for row in rows:
        valores = {
            nombre: (
                _normalize(row[index])
                if index is not None and index < len(row)
                else ""
            )
            for nombre, index in indices.items()
        }
        if filtros_texto["barrio"] and filtros_texto["barrio"] not in valores["barrio"]:
            continue
        if filtros_texto["metros"] and valores["metros"] != filtros_texto["metros"]:
            continue
        if filtros_texto["habitaciones"] and valores["habitaciones"] != filtros_texto["habitaciones"]:
            continue
        if filtros_texto["banos"] and valores["banos"] != filtros_texto["banos"]:
            continue
        resultados.append(dict(zip(headers, row)))

    return resultados


# ============================================
# TOOLS EXPORTABLES
# ============================================
@tool
def consultar_tipo_inmueble(identificador: str) -> str:
    """
    Consulta el tipo de un inmueble por ID o lista los tipos disponibles.

    Úsala cuando el usuario pregunte:
    - "¿Qué tipo de inmueble es BH-001?" (envía el ID exacto).
    - "¿Cuáles son los tipos de inmuebles?" (envía "lista").

    Args:
        identificador: ID exacto de la columna "ID Inmueble", o "lista" para
                       consultar los tipos disponibles.
    """
    logger.info("Consultando tipo de inmueble: identificador=%s", identificador)
    try:
        headers, rows = _cargar_datos()
        if _normalize(identificador) in {"lista", "listas", "tipos", "todos"}:
            tipos = _listar_tipos_inmueble(rows, headers)
            if not tipos:
                return "No encontré tipos de inmueble registrados."
            return "Tipos de inmueble disponibles:\n" + "\n".join(
                f"- {tipo}" for tipo in tipos
            )

        fila = _buscar_fila_inmueble(rows, headers, identificador)
        if not fila:
            return (
                f"No encontré un inmueble que coincida con '{identificador}'. "
                "Confirma el código o identificador del inmueble."
            )
        _, idx_tipo, _ = _columnas_inmueble(headers)
        if idx_tipo is None:
            return "La hoja no tiene la columna 'Tipo'."
        tipo = fila.get(headers[idx_tipo], "")
        return f"Tipo de inmueble: {tipo}" if tipo else "No encontré el tipo de inmueble registrado."
    except Exception as e:
        logger.exception("Error consultando tipo de inmueble: identificador=%s", identificador)
        return f"Error al consultar Google Sheets: {str(e)}"


@tool
def consultar_alquiler_inmueble(identificador: str) -> str:
    """
    Consulta el alquiler mensual usando el ID exacto del inmueble.

    Úsala cuando el usuario pregunte:
    - "¿Cuál es el alquiler del inmueble 301?"
    - "¿Cuánto cuesta alquilar el inmueble X?"

    Args:
        identificador: Valor de la columna "ID Inmueble", por ejemplo "BH-001".
    """
    logger.info("Consultando alquiler de inmueble: identificador=%s", identificador)
    try:
        headers, rows = _cargar_datos()
        fila = _buscar_fila_inmueble(rows, headers, identificador)
        if not fila:
            return (
                f"No encontré un inmueble que coincida con '{identificador}'. "
                "Confirma el código o identificador del inmueble."
            )
        _, _, idx_alquiler = _columnas_inmueble(headers)
        if idx_alquiler is None:
            return "La hoja no tiene la columna 'Alquiler Mensual (BRL)'."
        alquiler = fila.get(headers[idx_alquiler], "")
        return f"Alquiler del inmueble: {alquiler}" if alquiler else "No encontré el alquiler registrado."
    except Exception as e:
        logger.exception("Error consultando alquiler de inmueble: identificador=%s", identificador)
        return f"Error al consultar Google Sheets: {str(e)}"


@tool
def buscar_inmuebles(
    barrio: str = "",
    metros_cuadrados: str = "",
    habitaciones: str = "",
    banos: str = "",
) -> str:
    """
    Busca inmuebles por barrio, metros cuadrados, habitaciones y baños.

    Todos los filtros son opcionales, pero se debe enviar al menos uno.
    El barrio acepta coincidencias parciales. Los demás filtros son exactos.

    Ejemplos:
    - barrio="Barão Geraldo"
    - habitaciones="2", banos="1"
    - metros_cuadrados="65"
    """
    logger.info(
        "Buscando inmuebles: barrio=%s metros=%s habitaciones=%s banos=%s",
        barrio,
        metros_cuadrados,
        habitaciones,
        banos,
    )
    if not any((barrio, metros_cuadrados, habitaciones, banos)):
        return "Indica al menos un filtro: barrio, metros cuadrados, habitaciones o baños."

    try:
        headers, rows = _cargar_datos()
        resultados = _buscar_inmuebles_por_filtros(
            rows,
            headers,
            barrio,
            metros_cuadrados,
            habitaciones,
            banos,
        )
        if not resultados:
            return "No encontré inmuebles con esos criterios."

        indices = _indices_caracteristicas(headers)
        partes = [f"Inmuebles encontrados: {len(resultados)}"]
        for fila in resultados:
            inmueble_id = fila.get(headers[indices["id"]], "") if indices["id"] is not None else ""
            tipo = fila.get(headers[indices["tipo"]], "") if indices["tipo"] is not None else ""
            direccion = fila.get(headers[indices["direccion"]], "") if indices["direccion"] is not None else ""
            alquiler = fila.get(headers[indices["alquiler"]], "") if indices["alquiler"] is not None else ""
            partes.append(
                f"- ID: {inmueble_id}; Tipo: {tipo}; Dirección: {direccion}; "
                f"Alquiler mensual (BRL): {alquiler}"
            )
        return "\n".join(partes)
    except Exception as e:
        logger.exception("Error buscando inmuebles")
        return f"Error al consultar Google Sheets: {str(e)}"
