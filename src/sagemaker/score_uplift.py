'''
Puntúa la población solo_virtual (candidatos reales de la siguiente ola) con el
T-learner de train_uplift.py, y clasifica a cada cliente en los 4 segmentos:

- persuadible:   p_tratamiento alto, p_control bajo -- SOLO cambia con la tarjeta. PRIORIZAR.
- sure_thing:    p_tratamiento alto, p_control alto -- cambiaría igual, con o sin tarjeta. No usar presupuesto acá.
- lost_cause:    p_tratamiento bajo, p_control bajo -- no cambia ni con tarjeta. No usar presupuesto acá.
- sleeping_dog:  p_tratamiento bajo, p_control alto -- la tarjeta empeora el resultado. EVITAR.

Se escribe los resultados de la predicción en un S3 y también en DynamoDB para su consulta por API
'''

import argparse
import os
import sys
import joblib
import pandas as pd
from datetime import date
from decimal import Decimal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

UMBRAL_SEGMENTO = 0.5


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--cliente-360", type=str, default=None)
    p.add_argument("--model-path", type=str, default=None)
    p.add_argument("--output-dir", type=str, default=None)
    p.add_argument("--fecha", type=str, default=None, help="YYYY-MM-DD, default hoy")
    p.add_argument("--version-modelo", type=str, default="causalml_tlearner_v1")
    p.add_argument("--dynamodb-table", type=str, default=os.environ.get("DYNAMODB_TABLE"),
                    help="si no se da (ni está DYNAMODB_TABLE seteada), se omite el escrito a DynamoDB")
    p.add_argument("--region", type=str, default="us-east-1")
    return p.parse_args()


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def clasificar_segmento(p_tratamiento: float, p_control: float) -> str:
    
    alto_t = p_tratamiento >= UMBRAL_SEGMENTO
    alto_c = p_control >= UMBRAL_SEGMENTO
    
    if alto_t and not alto_c:
        return "persuadible"
    
    if alto_t and alto_c:
        return "sure_thing"
    
    if not alto_t and not alto_c:
        return "lost_cause"
    
    return "sleeping_dog"


def razon_principal(segmento: str, p_tratamiento: float, p_control: float) -> str:
    
    gap = p_tratamiento - p_control
    
    if segmento == "persuadible":
        return f"probabilidad de aumentar uso sube de {p_control:.0%} (sin tarjeta) a {p_tratamiento:.0%} (con tarjeta)"
    
    if segmento == "sure_thing":
        return f"probablemente aumentaría el uso de todas formas ({p_control:.0%} sin tarjeta, {p_tratamiento:.0%} con tarjeta)"
    
    if segmento == "lost_cause":
        return f"baja probabilidad de aumentar uso con ({p_tratamiento:.0%}) o sin ({p_control:.0%}) tarjeta"
    
    return f"la tarjeta podría REDUCIR la probabilidad de aumentar uso ({p_control:.0%} sin tarjeta vs. {p_tratamiento:.0%} con tarjeta, gap={gap:+.0%})"


def escribir_dynamodb(resultado: pd.DataFrame, fecha: str, table_name: str, region: str) -> None:
    '''
    Escribe cada fila como un item de DynamoDB (clave: cliente_id).
    '''
    
    import boto3

    tabla = boto3.resource("dynamodb", region_name=region).Table(table_name)
    
    with tabla.batch_writer() as writer:
        for fila in resultado.itertuples(index=False):
            writer.put_item(Item={
                "cliente_id": fila.cliente_id,
                "score_uplift": Decimal(str(round(fila.score_uplift, 6))),
                "p_tratamiento": Decimal(str(round(fila.p_tratamiento, 6))),
                "p_control": Decimal(str(round(fila.p_control, 6))),
                "segmento_uplift": fila.segmento_uplift,
                "razones_principales": fila.razones_principales,
                "version_modelo": fila.version_modelo,
                "fecha_calculo": fecha,
            })
    
    print(f"Escritos {len(resultado):,} items en DynamoDB ({table_name})")


def main():
    args = parse_args()
    base = repo_root()
    cliente_360_path = args.cliente_360 or f"{base}/data/curated/cliente_360"
    model_path = args.model_path or f"{base}/models/uplift/modelo_uplift_tlearner.joblib"
    fecha = args.fecha or date.today().isoformat()
    output_dir = args.output_dir or f"{base}/data/predictions/uplift_scores/dt={fecha}"
    os.makedirs(output_dir, exist_ok=True)

    artefacto = joblib.load(model_path)
    learner = artefacto["learner"]
    preprocesador = artefacto["preprocesador"]
    cols = artefacto["features_numericas"] + artefacto["features_categoricas"]

    cliente_360 = pd.read_parquet(cliente_360_path)
    poblacion = cliente_360[cliente_360["grupo_piloto"] == "solo_virtual"].copy()
    print(f"Puntuando {len(poblacion):,} clientes solo_virtual")

    X = preprocesador.transform(poblacion[cols])    
    p_control = learner.models_c[artefacto["treatment_name"]].predict_proba(X)[:, 1]
    p_tratamiento = learner.models_t[artefacto["treatment_name"]].predict_proba(X)[:, 1]
    score_uplift = p_tratamiento - p_control

    resultado = pd.DataFrame({
        "cliente_id": poblacion["cliente_id"].to_numpy(),
        "score_uplift": score_uplift,
        "p_tratamiento": p_tratamiento,
        "p_control": p_control,
    })
    resultado["segmento_uplift"] = [
        clasificar_segmento(pt, pc) for pt, pc in zip(p_tratamiento, p_control)
    ]
    resultado["razones_principales"] = [
        razon_principal(seg, pt, pc)
        for seg, pt, pc in zip(resultado["segmento_uplift"], p_tratamiento, p_control)
    ]
    resultado["version_modelo"] = args.version_modelo

    resultado.to_parquet(os.path.join(output_dir, "scores.parquet"), index=False)
    print(f"\nDistribución de segmentos:")
    print(resultado["segmento_uplift"].value_counts())
    print(f"Guardado (auditoría, S3/Glue) en {output_dir}")

    if args.dynamodb_table:
        escribir_dynamodb(resultado, fecha, args.dynamodb_table, args.region)
    
    else:
        print("\n--dynamodb-table no especificada (ni DYNAMODB_TABLE en el entorno) "
              "-- se omite el escrito a DynamoDB, solo queda en S3/Glue.")


if __name__ == "__main__":
    main()
