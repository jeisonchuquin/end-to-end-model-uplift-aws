'''
Glue Job 1 (bronze -> silver): estandariza los 5 datasets de data/raw.

Se realiza la limpieza y estandarización de las columnas, dependiendo del entorno de
ejecución puede correr en Glue o en local.

La limpieza trata de corregir lo encontrado en el notebook 00_data_standard_valid.ipynb

En este job se envía a quarentine/ casos ambiguos como por ejemplo datos negativos de montos,
clientes sin tarjeta, pero se aplica un motivo de envío.
'''

import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from utils.fechas import parsear_fecha_multiformato
from utils.normalizacion import (
    limpiar_cedula,
    mapear_con_excepciones,
    normalizar_codigo,
    normalizar_nombre_propio,
    parsear_booleano,
    texto_o_null,
)
from utils.spark_boot import EN_GLUE, base_local, get_spark_y_args


def get_spark_y_rutas():
    base = base_local()
    spark, args, job = get_spark_y_args(
        "peigo-standardize",
        ["input_path", "output_path", "quarantine_path"],
        {
            "input_path": f"{base}/data/raw",
            "output_path": f"{base}/data/processed",
            "quarantine_path": f"{base}/data/quarantine",
        },
    )
    
    return spark, args["input_path"], args["output_path"], args["quarantine_path"], job


def con_motivo(df: DataFrame, motivo: str) -> DataFrame:
    '''
    Setea el motivo de descarte y envío a quarantine
    '''
    
    return df.withColumn("motivo_descarte", F.lit(motivo)).withColumn(
        "fecha_proceso", F.current_timestamp()
    )



# CLIENTES

def clean_clientes(df: DataFrame):
    df = df.dropDuplicates()

    fecha_nac = parsear_fecha_multiformato(F.col("fecha_nacimiento"))
    edad = F.floor(F.datediff(F.current_date(), fecha_nac) / 365.25)
    edad_valida = fecha_nac.isNotNull() & (edad >= 18) & (edad <= 100)

    ventana_cedula = Window.partitionBy("cedula")

    df = (
        df.withColumn("cliente_id", F.trim(F.col("cliente_id")))
        .withColumn("cedula", limpiar_cedula(F.col("cedula")))
        .withColumn("fecha_nacimiento", F.when(edad_valida, fecha_nac))
        .withColumn("fecha_nacimiento_valida", edad_valida)
        .withColumn("edad", F.when(edad_valida, edad))
        .withColumn("ciudad", normalizar_nombre_propio(F.col("ciudad")))
        .withColumn("canal_adquisicion", texto_o_null(F.col("canal_adquisicion")))
        .withColumn(
            "canal_adquisicion",
            F.when(
                F.col("canal_adquisicion").isNotNull(),
                normalizar_codigo(F.col("canal_adquisicion")),
            ),
        )
        .withColumn("estado_cuenta", normalizar_codigo(F.col("estado_cuenta")))
        .withColumn("fecha_registro", parsear_fecha_multiformato(F.col("fecha_registro")))
        .withColumn("cedula_duplicada", F.count("*").over(ventana_cedula) > 1)
    )
    return df, None



# TARJETAS

def clean_tarjetas(df: DataFrame, cliente_ids_validos: DataFrame):
    df = df.dropDuplicates()

    tipo_normalizado = mapear_con_excepciones(
        normalizar_codigo(F.col("tipo")), {"f": "fisica", "v": "virtual"}
    )

    df = (
        df.withColumn("tarjeta_id", F.trim(F.col("tarjeta_id")))
        .withColumn("cliente_id", F.trim(F.col("cliente_id")))
        .withColumn("tipo", tipo_normalizado)
        .withColumn("fecha_emision", parsear_fecha_multiformato(F.col("fecha_emision")))
        .withColumn("fecha_activacion", parsear_fecha_multiformato(F.col("fecha_activacion")))
        .withColumn(
            "fisica_activada",
            (F.col("tipo") == "fisica") & F.col("fecha_activacion").isNotNull(),
        )
        .withColumn("dias_hasta_activacion", F.datediff("fecha_activacion", "fecha_emision"))
        # se categoriza el estado_codigo.
        # .withColumn(
        #     "estado_codigo_hipotesis",
        #     F.when(F.col("estado_codigo") == 1, "emitida_hipotesis")
        #     .when(F.col("estado_codigo") == 2, "activada_o_emitida_hipotesis_ambiguo")
        #     .when(F.col("estado_codigo") == 3, "bloqueada_o_cancelada_hipotesis"),
        # )
    )

    validos = df.join(cliente_ids_validos, on="cliente_id", how="left_semi")
    huerfanos = con_motivo(
        df.join(cliente_ids_validos, on="cliente_id", how="left_anti"), "cliente_id_huerfano"
    )
    
    return validos, huerfanos



# TRANSACCIONES

def clean_transacciones(df: DataFrame, cliente_ids_validos: DataFrame):
    df = df.dropDuplicates()

    monto_limpio = F.regexp_replace(F.trim(F.col("monto")), r"[$,]", "").cast("decimal(12,2)")

    df = (
        df.withColumn("transaccion_id", F.trim(F.col("transaccion_id")))
        .withColumn("cliente_id", F.trim(F.col("cliente_id")))
        .withColumn("fecha", parsear_fecha_multiformato(F.col("fecha")))
        .withColumn("tipo_transaccion", normalizar_codigo(F.col("tipo_transaccion")))
        .withColumn("monto", monto_limpio)
        .withColumn("comercio_codigo", F.trim(F.col("comercio_codigo")))
        .withColumn("es_devolucion", parsear_booleano(F.col("es_devolucion")))
    )

    # cliente_id huérfano
    con_cliente_valido = df.join(cliente_ids_validos, on="cliente_id", how="left_semi")
    huerfanos_cliente = con_motivo(
        df.join(cliente_ids_validos, on="cliente_id", how="left_anti"), "cliente_id_huerfano"
    )
    
    # los montos negativos no corresponden a salidas, no es concluyente, por lo que se envía a quarantine
    validos = con_cliente_valido.filter((F.col("monto") >= 0) | F.col("monto").isNull())
    monto_invalido = con_motivo(
        con_cliente_valido.filter(F.col("monto") < 0), "monto_negativo_invalido"
    )

    quarantine = huerfanos_cliente.unionByName(monto_invalido, allowMissingColumns=True)
    
    return validos, quarantine



# INTERACCIONES DE MARKETING

def clean_marketing(df: DataFrame, cliente_ids_validos: DataFrame):
    df = df.dropDuplicates()

    df = (
        df.withColumn("interaccion_id", F.trim(F.col("interaccion_id")))
        .withColumn("cliente_id", F.trim(F.col("cliente_id")))
        .withColumn("campana", normalizar_nombre_propio(F.col("campana")))
        .withColumn("fecha_contacto", parsear_fecha_multiformato(F.col("fecha_contacto")))
        .withColumn("canal", normalizar_codigo(F.col("canal")))
        .withColumn("respondio", parsear_booleano(F.col("respondio")))
    )

    validos = df.join(cliente_ids_validos, on="cliente_id", how="left_semi")
    huerfanos = con_motivo(
        df.join(cliente_ids_validos, on="cliente_id", how="left_anti"), "cliente_id_huerfano"
    )
    
    return validos, huerfanos



# CATALOGO DE COMERCIOS

# Se realiza una reasignación de categoria de los comercios y se cambia cambia de categoría de
# serivicios_publicos a telefonia
CORRECCION_CATEGORIA_COMERCIOS = {
    "Uber": "transporte",
    "Cabify": "transporte",
    "Mi Comisariato": "supermercado",
    "Supermaxi": "supermercado",
    "Spotify": "streaming",
    "Netflix": "streaming",
    "CNT": "telefonia",
    "Movistar": "telefonia",
    "Claro": "telefonia",
    "Farmacias Cruz Azul": "salud",
    "De Prati": "retail",
    "KFC": "restaurante",
    "Pizza Hut": "restaurante",
    "McDonalds": "restaurante",
    "Cinemark": "entretenimiento",
}


def clean_comercios(df: DataFrame):
    df = df.dropDuplicates().withColumn("comercio_codigo", F.trim(F.col("comercio_codigo")))

    mapa_correccion = F.create_map(
        [F.lit(x) for par in CORRECCION_CATEGORIA_COMERCIOS.items() for x in par]
    )
    df = df.withColumn(
        "categoria", F.coalesce(mapa_correccion.getItem(F.col("nombre_comercio")), F.col("categoria"))
    )
    return df, None


def escribir(df: DataFrame, ruta: str):
    df.write.mode("overwrite").parquet(ruta)


def main():
    spark, input_path, output_path, quarantine_path, job = get_spark_y_rutas()

    tablas_raw = {
        "clientes": spark.read.parquet(f"{input_path}/clientes.parquet"),
        "tarjetas": spark.read.parquet(f"{input_path}/tarjetas.parquet"),
        "transacciones": spark.read.parquet(f"{input_path}/transacciones.parquet"),
        "interacciones_marketing": spark.read.parquet(f"{input_path}/interacciones_marketing.parquet"),
        "catalogo_comercios": spark.read.parquet(f"{input_path}/catalogo_comercios.parquet"),
    }

    reporte = {}

    clientes_ok, _ = clean_clientes(tablas_raw["clientes"])
    clientes_ok.cache()
    cliente_ids_validos = clientes_ok.select("cliente_id").distinct()

    tarjetas_ok, tarjetas_q = clean_tarjetas(tablas_raw["tarjetas"], cliente_ids_validos)
    transacciones_ok, transacciones_q = clean_transacciones(tablas_raw["transacciones"], cliente_ids_validos)
    marketing_ok, marketing_q = clean_marketing(tablas_raw["interacciones_marketing"], cliente_ids_validos)
    comercios_ok, _ = clean_comercios(tablas_raw["catalogo_comercios"])

    salidas_procesadas = {
        "clientes": clientes_ok,
        "tarjetas": tarjetas_ok,
        "transacciones": transacciones_ok,
        "interacciones_marketing": marketing_ok,
        "catalogo_comercios": comercios_ok,
    }
    salidas_cuarentena = {
        "tarjetas": tarjetas_q,
        "transacciones": transacciones_q,
        "interacciones_marketing": marketing_q,
    }

    for nombre, df in salidas_procesadas.items():
        escribir(df, f"{output_path}/{nombre}")
        reporte[nombre] = {
            "filas_crudas": tablas_raw[nombre].count(),
            "filas_procesadas": df.count(),
        }

    for nombre, df in salidas_cuarentena.items():
        if df is not None and df.take(1):
            escribir(df, f"{quarantine_path}/{nombre}")
            reporte[nombre]["filas_cuarentena"] = df.count()
            reporte[nombre]["motivos_cuarentena"] = {
                row["motivo_descarte"]: row["n"]
                for row in df.groupBy("motivo_descarte").count().withColumnRenamed("count", "n").collect()
            }
        else:
            reporte[nombre]["filas_cuarentena"] = 0

    print(json.dumps(reporte, indent=2, ensure_ascii=False))

    if EN_GLUE and job is not None:
        job.commit()


if __name__ == "__main__":
    main()
