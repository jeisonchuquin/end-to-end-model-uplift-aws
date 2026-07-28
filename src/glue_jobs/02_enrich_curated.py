'''
Glue Job 2 (silver -> gold): resuelve joins y construye la capa de negocio.

Produce dos tablas en curated/:
    - cliente_360: una fila por cliente_id, con la variable de tratamiento del piloto
    y las features de actividad transaccional/marketing/demográficas.
    - piloto_pilot_summary: agregados por grupo_piloto, para realizar análisis de rendimiento
'''

import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from utils.spark_boot import EN_GLUE, base_local, get_spark_y_args

DIAS_POR_MES = 30.44

# Mínimo de días de ventana para que una tasa mensual (transacciones/mes, monto/mes) se considere confiable. 
DIAS_MINIMOS_PARA_TASA = 30


def tasa_mensual_confiable(numerador, dias_ventana):
    
    return F.when(
        dias_ventana >= DIAS_MINIMOS_PARA_TASA,
        numerador / (dias_ventana / F.lit(DIAS_POR_MES)),
    )


def get_spark_y_rutas():
    
    base = base_local()
    spark, args, job = get_spark_y_args(
        "peigo-enrich-curated",
        ["input_path", "output_path"],
        {"input_path": f"{base}/data/processed", "output_path": f"{base}/data/curated"},
    )
    
    return spark, args["input_path"], args["output_path"], job



# Agregación de tarjetas: variable de tratamiento del piloto

def agregar_tarjetas(tarjetas: DataFrame) -> DataFrame:
    '''
    Se asume una sola tarjeta física "del piloto" por cliente, la de emisión más
    antigua si hubiera más de una.
    '''
    
    return tarjetas.groupBy("cliente_id").agg(
        F.max(F.col("tipo") == "fisica").alias("tiene_tarjeta_fisica"),
        F.max(F.coalesce(F.col("fisica_activada"), F.lit(False))).alias("fisica_activada"),
        F.min(F.when(F.col("tipo") == "fisica", F.col("fecha_emision"))).alias("fecha_emision_fisica"),
        F.min(F.when(F.col("tipo") == "fisica", F.col("fecha_activacion"))).alias("fecha_activacion_fisica"),
    )


def derivar_grupo_piloto(df: DataFrame) -> DataFrame:
    
    tiene_tarjeta = F.col("tiene_alguna_tarjeta")
    
    return df.withColumn(
        "grupo_piloto",
        F.when(F.col("fisica_activada"), "fisica_activa")
        .when(F.col("tiene_tarjeta_fisica"), "fisica_no_activa")
        .when(tiene_tarjeta, "solo_virtual")
        .otherwise("sin_tarjeta_registrada"),
    ).withColumn(
        "dias_hasta_activacion",
        F.datediff(F.col("fecha_activacion_fisica"), F.col("fecha_emision_fisica")),
    )



# Agregación de transacciones

TIPOS_TRANSACCION_VALIDOS = [
    "cash_in", "cash_out", "p2p_in", "p2p_out",
    "compra_tarjeta", "recarga_celular", "pago_servicio", "remesa",
]


def agregar_transacciones(transacciones: DataFrame, comercios: DataFrame) -> DataFrame:
    
    tx = transacciones.join(comercios, on="comercio_codigo", how="left").withColumn(
        "categoria_comercio",
        F.when(F.col("comercio_codigo").isNotNull(), F.coalesce(F.col("categoria"), F.lit("otros_no_catalogado"))),
    )

    resumen = tx.groupBy("cliente_id").agg(
        F.count("*").alias("n_transacciones_total"),
        F.sum("monto").cast("double").alias("monto_total"),
        F.avg("monto").cast("double").alias("monto_promedio"),
        F.min("fecha").alias("primera_transaccion"),
        F.max("fecha").alias("ultima_transaccion"),
        F.countDistinct("categoria_comercio").alias("n_categorias_comercio_distintas"),
    )

    pivot = (
        tx.groupBy("cliente_id")
        .pivot("tipo_transaccion", TIPOS_TRANSACCION_VALIDOS)
        .count()
        .na.fill(0)
    )
    for c in TIPOS_TRANSACCION_VALIDOS:
        pivot = pivot.withColumnRenamed(c, f"n_{c}")

    return resumen.join(pivot, on="cliente_id", how="left").withColumn(
        "pct_compra_tarjeta_sobre_total",
        F.col("n_compra_tarjeta") / F.col("n_transacciones_total"),
    )


def agregar_transacciones_pre_post(transacciones: DataFrame, tarjetas_agg: DataFrame) -> DataFrame:
    '''
    Compara actividad antes/después de la activación de la tarjeta física,
    normalizada por días de cada ventana.
    '''
    
    base = transacciones.join(
        tarjetas_agg.select("cliente_id", "fecha_activacion_fisica"), on="cliente_id", how="inner"
    ).filter(F.col("fecha_activacion_fisica").isNotNull())

    pre = base.filter(F.col("fecha") < F.col("fecha_activacion_fisica")).groupBy("cliente_id").agg(
        F.count("*").alias("n_transacciones_pre"),
        F.sum("monto").cast("double").alias("monto_pre"),
    )
    post = base.filter(F.col("fecha") >= F.col("fecha_activacion_fisica")).groupBy("cliente_id").agg(
        F.count("*").alias("n_transacciones_post"),
        F.sum("monto").cast("double").alias("monto_post"),
    )
    return pre.join(post, on="cliente_id", how="outer")


def agregar_transacciones_pre_emision(transacciones: DataFrame, tarjetas_agg: DataFrame, comercios: DataFrame) -> DataFrame:
    '''
    Actividad transaccional ANTES de que el cliente recibiera la tarjeta física
    (fecha_emision_fisica), no de que la activara.
    '''
    
    base = (
        transacciones.join(
            tarjetas_agg.select("cliente_id", "fecha_emision_fisica"), on="cliente_id", how="inner"
        )
        .filter(F.col("fecha_emision_fisica").isNotNull() & (F.col("fecha") < F.col("fecha_emision_fisica")))
        .join(comercios, on="comercio_codigo", how="left")
        .withColumn(
            "categoria_comercio",
            F.when(F.col("comercio_codigo").isNotNull(), F.coalesce(F.col("categoria"), F.lit("otros_no_catalogado"))),
        )
    )

    return base.groupBy("cliente_id").agg(
        F.count("*").alias("n_transacciones_pre_emision"),
        F.sum("monto").cast("double").alias("monto_pre_emision"),
        F.sum(F.when(F.col("tipo_transaccion") == "compra_tarjeta", 1).otherwise(0)).alias(
            "n_compra_tarjeta_pre_emision"
        ),
        F.countDistinct("categoria_comercio").alias("n_categorias_comercio_pre_emision"),
    )



# Agregación de marketing

def agregar_marketing(marketing: DataFrame) -> DataFrame:
    
    return marketing.groupBy("cliente_id").agg(
        F.count("*").alias("n_interacciones_marketing"),
        F.countDistinct("campana").alias("n_campanas_distintas"),
        F.avg(F.col("respondio").cast("int")).alias("tasa_respuesta"),
        F.max("fecha_contacto").alias("ultima_interaccion_marketing"),
    )


def agregar_marketing_pre_emision(marketing: DataFrame, tarjetas_agg: DataFrame) -> DataFrame:
    '''
    Igual razonamiento que agregar_transacciones_pre_emision
    '''
    
    base = marketing.join(
        tarjetas_agg.select("cliente_id", "fecha_emision_fisica"), on="cliente_id", how="inner"
    ).filter(F.col("fecha_emision_fisica").isNotNull() & (F.col("fecha_contacto") < F.col("fecha_emision_fisica")))

    return base.groupBy("cliente_id").agg(
        F.count("*").alias("n_interacciones_pre_emision"),
        F.avg(F.col("respondio").cast("int")).alias("tasa_respuesta_pre_emision"),
    )


def main():
    spark, input_path, output_path, job = get_spark_y_rutas()

    clientes = spark.read.parquet(f"{input_path}/clientes")
    tarjetas = spark.read.parquet(f"{input_path}/tarjetas")
    transacciones = spark.read.parquet(f"{input_path}/transacciones")
    marketing = spark.read.parquet(f"{input_path}/interacciones_marketing")
    comercios = spark.read.parquet(f"{input_path}/catalogo_comercios")

    tarjetas_agg = agregar_tarjetas(tarjetas)
    tx_agg = agregar_transacciones(transacciones, comercios)
    tx_prepost = agregar_transacciones_pre_post(transacciones, tarjetas_agg)
    tx_pre_emision = agregar_transacciones_pre_emision(transacciones, tarjetas_agg, comercios)
    marketing_agg = agregar_marketing(marketing)
    marketing_pre_emision = agregar_marketing_pre_emision(marketing, tarjetas_agg)

    hoy = F.current_date()

    presentes_en_tarjetas = tarjetas.select("cliente_id").distinct().withColumn("tiene_alguna_tarjeta", F.lit(True))

    cliente_360 = (
        clientes
        .join(tarjetas_agg, on="cliente_id", how="left")
        .join(presentes_en_tarjetas, on="cliente_id", how="left")
        .withColumn("tiene_alguna_tarjeta", F.coalesce(F.col("tiene_alguna_tarjeta"), F.lit(False)))
        .withColumn("tiene_tarjeta_fisica", F.coalesce(F.col("tiene_tarjeta_fisica"), F.lit(False)))
        .withColumn("fisica_activada", F.coalesce(F.col("fisica_activada"), F.lit(False)))
    )
    cliente_360 = derivar_grupo_piloto(cliente_360)

    cliente_360 = (
        cliente_360
        .join(tx_agg, on="cliente_id", how="left")
        .join(tx_prepost, on="cliente_id", how="left")
        .join(tx_pre_emision, on="cliente_id", how="left")
        .join(marketing_agg, on="cliente_id", how="left")
        .join(marketing_pre_emision, on="cliente_id", how="left")
    )

    columnas_conteo = [c for c in cliente_360.columns if c.startswith("n_")]
    for c in columnas_conteo:
        cliente_360 = cliente_360.withColumn(c, F.coalesce(F.col(c), F.lit(0)))

    cliente_360 = (
        cliente_360
        .withColumn("antiguedad_dias", F.datediff(hoy, F.col("fecha_registro")))
        .withColumn("dias_desde_ultima_transaccion", F.datediff(hoy, F.col("ultima_transaccion")))
        .withColumn("frecuencia_mensual", tasa_mensual_confiable(F.col("n_transacciones_total"), F.col("antiguedad_dias")))
        .withColumn("monto_mensual", tasa_mensual_confiable(F.col("monto_total"), F.col("antiguedad_dias")))
        .withColumn("dias_pre", F.datediff(F.col("fecha_activacion_fisica"), F.col("fecha_registro")))
        .withColumn("dias_post", F.datediff(hoy, F.col("fecha_activacion_fisica")))
        .withColumn("frecuencia_mensual_pre", tasa_mensual_confiable(F.col("n_transacciones_pre"), F.col("dias_pre")))
        .withColumn("frecuencia_mensual_post", tasa_mensual_confiable(F.col("n_transacciones_post"), F.col("dias_post")))        
        .withColumn("monto_mensual_pre", tasa_mensual_confiable(F.col("monto_pre"), F.col("dias_pre")))
        .withColumn("monto_mensual_post", tasa_mensual_confiable(F.col("monto_post"), F.col("dias_post")))
        .withColumn("dias_desde_ultima_interaccion_marketing", F.datediff(hoy, F.col("ultima_interaccion_marketing")))
        .withColumn("dias_pre_emision", F.datediff(F.col("fecha_emision_fisica"), F.col("fecha_registro")))
        .withColumn(
            "frecuencia_mensual_pre_emision",
            tasa_mensual_confiable(F.col("n_transacciones_pre_emision"), F.col("dias_pre_emision")),
        )
        .withColumn(
            "monto_mensual_pre_emision",
            tasa_mensual_confiable(F.col("monto_pre_emision"), F.col("dias_pre_emision")),
        )
        .withColumn(
            "pct_compra_tarjeta_pre_emision",
            F.when(
                F.col("n_transacciones_pre_emision") > 0,
                F.col("n_compra_tarjeta_pre_emision") / F.col("n_transacciones_pre_emision"),
            ),
        )
    )

    tiene_fecha_emision = F.col("fecha_emision_fisica").isNotNull()

    cliente_360 = (
        cliente_360
        .withColumn(
            "feat_frecuencia_mensual",
            F.when(tiene_fecha_emision, F.col("frecuencia_mensual_pre_emision")).otherwise(F.col("frecuencia_mensual")),
        )
        .withColumn(
            "feat_monto_mensual",
            F.when(tiene_fecha_emision, F.col("monto_mensual_pre_emision")).otherwise(F.col("monto_mensual")),
        )
        .withColumn(
            "feat_pct_compra_tarjeta",
            F.when(tiene_fecha_emision, F.col("pct_compra_tarjeta_pre_emision")).otherwise(F.col("pct_compra_tarjeta_sobre_total")),
        )
        .withColumn(
            "feat_n_categorias_comercio",
            F.when(tiene_fecha_emision, F.col("n_categorias_comercio_pre_emision")).otherwise(F.col("n_categorias_comercio_distintas")),
        )
        .withColumn(
            "feat_n_interacciones_marketing",
            F.when(tiene_fecha_emision, F.col("n_interacciones_pre_emision")).otherwise(F.col("n_interacciones_marketing")),
        )
        .withColumn(
            "feat_tasa_respuesta_marketing",
            F.when(tiene_fecha_emision, F.col("tasa_respuesta_pre_emision")).otherwise(F.col("tasa_respuesta")),
        )
        .withColumn("feat_edad", F.col("edad"))
        .withColumn("feat_antiguedad_dias", F.when(F.col("antiguedad_dias") > 0, F.col("antiguedad_dias")))
        .withColumn("feat_ciudad", F.col("ciudad"))
        .withColumn("feat_canal_adquisicion", F.col("canal_adquisicion"))
    )

    cliente_360.write.mode("overwrite").parquet(f"{output_path}/cliente_360")

    piloto_pilot_summary = cliente_360.groupBy("grupo_piloto").agg(
        F.count("*").alias("n_clientes"),
        F.avg("n_transacciones_total").alias("avg_n_transacciones_total"),
        F.expr("percentile_approx(n_transacciones_total, 0.5)").alias("mediana_n_transacciones_total"),
        F.avg("monto_total").alias("avg_monto_total"),
        F.expr("percentile_approx(monto_total, 0.5)").alias("mediana_monto_total"),
        F.avg("frecuencia_mensual_pre").alias("avg_frecuencia_mensual_pre"),
        F.avg("frecuencia_mensual_post").alias("avg_frecuencia_mensual_post"),
        F.avg("monto_mensual_pre").alias("avg_monto_mensual_pre"),
        F.avg("monto_mensual_post").alias("avg_monto_mensual_post"),
        F.avg("tasa_respuesta").alias("avg_tasa_respuesta_marketing"),
    )
    piloto_pilot_summary.write.mode("overwrite").parquet(f"{output_path}/piloto_pilot_summary")

    n_total = clientes.count()
    resumen = {
        row["grupo_piloto"]: row["n_clientes"]
        for row in cliente_360.groupBy("grupo_piloto").count().withColumnRenamed("count", "n_clientes").collect()
    }
    print(json.dumps({"n_clientes_total": n_total, "distribucion_grupo_piloto": resumen}, indent=2, ensure_ascii=False))

    if EN_GLUE and job is not None:
        job.commit()


if __name__ == "__main__":
    main()
