'''
Lambda detrás de GET /clientes/{cliente_id}/uplift.

Consulta DynamoDB, GetItem por `cliente_id`, un dígito de milisegundos
'''

import json
import os
from decimal import Decimal

import boto3

DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]

dynamodb = boto3.resource("dynamodb")
tabla = dynamodb.Table(DYNAMODB_TABLE)

SEGMENTO_DESCRIPCION = {
    "persuadible": "Alta prioridad: es más probable que aumente su actividad SI recibe la tarjeta física, y no lo haría por su cuenta.",
    "sure_thing": "Baja prioridad: probablemente aumentaría su actividad con o sin la tarjeta -- darle la tarjeta no cambia el resultado.",
    "lost_cause": "Baja prioridad: es poco probable que aumente su actividad, con o sin la tarjeta.",
    "sleeping_dog": "No priorizar: el modelo estima que darle la tarjeta podría REDUCIR su actividad respecto a dejarlo solo con virtual.",
}


def _respuesta(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _cliente_id_del_evento(event: dict) -> str | None:
    path_params = event.get("pathParameters") or {}
    return path_params.get("cliente_id")


def _a_float(valor) -> float | None:
    return float(valor) if isinstance(valor, Decimal) else valor


def handler(event, context):
    cliente_id = _cliente_id_del_evento(event)
    if not cliente_id:
        return _respuesta(400, {"error": "Falta cliente_id en la ruta"})

    try:
        item = tabla.get_item(Key={"cliente_id": cliente_id}).get("Item")
    except Exception as e:  # boto3.ClientError u otro fallo de DynamoDB
        return _respuesta(502, {"error": "No se pudo consultar DynamoDB", "detalle": str(e)})

    if not item:
        return _respuesta(404, {"error": f"No hay score de uplift para cliente_id={cliente_id}"})

    segmento = item.get("segmento_uplift")
    respuesta = {
        "cliente_id": item.get("cliente_id"),
        "score_uplift": _a_float(item.get("score_uplift")),
        "p_tratamiento": _a_float(item.get("p_tratamiento")),
        "p_control": _a_float(item.get("p_control")),
        "segmento_uplift": segmento,
        "segmento_descripcion": SEGMENTO_DESCRIPCION.get(segmento, ""),
        "razones_principales": item.get("razones_principales"),
        "version_modelo": item.get("version_modelo"),
        "fecha_calculo": item.get("fecha_calculo"),
    }
    return _respuesta(200, respuesta)
