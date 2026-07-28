import datetime

from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from utils.fechas import parsear_fecha_multiformato

SCHEMA = StructType([StructField("fecha", StringType(), True)])


def parsear(spark, entrada):
    df = spark.createDataFrame([(v,) for v in entrada], schema=SCHEMA)
    filas = df.select(parsear_fecha_multiformato(F.col("fecha")).alias("f")).collect()
    return [row["f"] for row in filas]


def test_parsea_formato_iso(spark):
    assert parsear(spark, ["2023-01-21"]) == [datetime.date(2023, 1, 21)]


def test_parsea_formato_dd_mm_yyyy(spark):
    assert parsear(spark, ["20/09/2024"]) == [datetime.date(2024, 9, 20)]


def test_parsea_epoch_ms_recientes_13_digitos(spark):
    # 1694044800000 ms == 2023-09-07
    assert parsear(spark, ["1694044800000"]) == [datetime.date(2023, 9, 7)]


def test_parsea_epoch_ms_antiguas_menos_de_13_digitos(spark):
    # 455889600000 ms == 1984-06-12 (fechas de nacimiento viejas no siempre tienen 13 dígitos)
    assert parsear(spark, ["455889600000"]) == [datetime.date(1984, 6, 12)]


def test_formato_no_reconocido_da_null(spark):
    assert parsear(spark, ["31 de marzo"]) == [None]


def test_valor_nulo_da_null(spark):
    assert parsear(spark, [None]) == [None]
