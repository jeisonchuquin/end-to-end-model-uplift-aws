from pyspark.sql import functions as F

from utils.normalizacion import (
    limpiar_cedula,
    mapear_con_excepciones,
    normalizar_codigo,
    normalizar_nombre_propio,
    normalizar_texto,
    parsear_booleano,
    texto_o_null,
)


def valores(spark, columna, entrada, funcion):
    df = spark.createDataFrame([(v,) for v in entrada], [columna])
    return [row[0] for row in df.select(funcion(F.col(columna))).collect()]


def test_normalizar_texto_quita_espacios_mayus_y_tildes(spark):
    entrada = [" Quito", "QUITO", "quito", "Fisica", "física", "FISICA"]
    salida = valores(spark, "c", entrada, normalizar_texto)
    assert salida == ["quito", "quito", "quito", "fisica", "fisica", "fisica"]


def test_normalizar_codigo_reemplaza_espacios_por_guion_bajo(spark):
    entrada = ["Cash In", "CASH_IN", " cash_in", "P2P Out"]
    salida = valores(spark, "c", entrada, normalizar_codigo)
    assert salida == ["cash_in", "cash_in", "cash_in", "p2p_out"]


def test_normalizar_nombre_propio_da_title_case(spark):
    entrada = ["QUITO", "guayaquil", " Cuenca"]
    salida = valores(spark, "c", entrada, normalizar_nombre_propio)
    assert salida == ["Quito", "Guayaquil", "Cuenca"]


def test_texto_o_null_unifica_variantes_de_nulo(spark):
    entrada = ["None", "N/A", "NULL", "", "organico", None]
    salida = valores(spark, "c", entrada, texto_o_null)
    assert salida == [None, None, None, None, "organico", None]


def test_parsear_booleano_unifica_representaciones(spark):
    entrada = ["True", "true", "TRUE", "1", "S", "Si", "False", "false", "FALSE", "0", "N", "No", "nan", ""]
    salida = valores(spark, "c", entrada, parsear_booleano)
    esperado = [True] * 6 + [False] * 6 + [None, None]
    assert salida == esperado


def test_limpiar_cedula_deja_solo_digitos(spark):
    entrada = ["174342225-8", "1308979008", " 1251834072 "]
    salida = valores(spark, "c", entrada, limpiar_cedula)
    assert salida == ["1743422258", "1308979008", "1251834072"]


def test_mapear_con_excepciones_expande_abreviaturas(spark):
    def f(col):
        return mapear_con_excepciones(col, {"f": "fisica", "v": "virtual"})

    entrada = ["f", "v", "fisica", "virtual"]
    salida = valores(spark, "c", entrada, f)
    assert salida == ["fisica", "virtual", "fisica", "virtual"]
