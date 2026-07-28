'''
Funciones de limpieza de texto/booleanos reutilizadas por los Glue Jobs.

Basadas en los valores reales encontrados en el notebook 00_data_standard_valid.ipynb:
mezcla de mayúsculas/minúsculas, espacios sobrantes, tildes, y booleanos representados
de ~10 formas distintas (True/False/TRUE/1/0/S/N/Si/No/Sí/nan).
'''

from pyspark.sql import Column
from pyspark.sql import functions as F

_TILDES = {
    "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
    "Á": "a", "É": "e", "Í": "i", "Ó": "o", "Ú": "u",
}

NULL_STRINGS = ("", "none", "n/a", "null", "nan")
BOOLEANOS_VERDADERO = ("true", "1", "s", "si")
BOOLEANOS_FALSO = ("false", "0", "n", "no")


def quitar_tildes(col: Column) -> Column:
    '''
    Quita las tildes de las palabras.
    
    Params:
        col: Columna a corregir
    '''
    
    resultado = col
    for con_tilde, sin_tilde in _TILDES.items():
        resultado = F.regexp_replace(resultado, con_tilde, sin_tilde)
    
    return resultado


def normalizar_texto(col: Column) -> Column:
    '''
    Se aplican: trim + colapsar espacios + minúsculas + sin tildes. Preserva espacios entre palabras.
    
    Params:
        col: Columna a corregir
    '''
    c = F.trim(col)
    c = F.regexp_replace(c, r"\s+", " ")
    c = F.lower(c)
    c = quitar_tildes(c)
    
    return c


def normalizar_codigo(col: Column) -> Column:
    '''
    Normalizar_texto + espacios -> guion_bajo. Para campos tipo código (cash_in, activa, fisica...).
    
    Params:
        col: Columna a corregir
    '''
    
    return F.regexp_replace(normalizar_texto(col), r"\s+", "_")


def normalizar_nombre_propio(col: Column) -> Column:
    '''
    Normalizar_texto + Title Case. Para campos de display (ciudad, nombre de campaña).
    
    Params:
        col: Columna a corregir
    '''
    
    return F.initcap(normalizar_texto(col))


def texto_o_null(col: Column) -> Column:
    '''
    Unifica las variantes de 'nulo como texto' (None/N/A/NULL/vacío/nan) a NULL real.
    
    Params:
        col: Columna a corregir
    '''
    
    norm = normalizar_texto(col)
    
    return F.when(norm.isin(*NULL_STRINGS), F.lit(None).cast("string")).otherwise(col)


def parsear_booleano(col: Column) -> Column:
    '''
    Unifica True/False/TRUE/FALSE/1/0/S/N/Si/No/Sí a boolean real.

    El string literal "nan" (y vacío) se trata como valor faltante, no como falso.
    
    Params:
        col: Columna a corregir
    '''
    
    norm = normalizar_texto(col)
    
    return (
        F.when(norm.isin("nan", ""), F.lit(None).cast("boolean"))
        .when(norm.isin(*BOOLEANOS_VERDADERO), F.lit(True))
        .when(norm.isin(*BOOLEANOS_FALSO), F.lit(False))
        .otherwise(F.lit(None).cast("boolean"))
    )


def limpiar_cedula(col: Column) -> Column:
    '''
    Deja solo dígitos. Estandariza el formato con guion (XXXXXXXXX-X, 11 chars) al
    formato plano de 10 dígitos que usa la mayoría de la base.
    
    Params:
        col: Columna a corregir
    '''
    
    return F.regexp_replace(F.trim(col), r"[^0-9]", "")


def mapear_con_excepciones(col: Column, excepciones: dict) -> Column:
    '''
    Devuelve el valor normalizado tal cual, salvo que esté en `excepciones`
    (usado para abreviaturas como tarjetas.tipo: F->fisica, V->virtual).
    
    Params:
        col: Columna a corregir
    '''
    
    mapa = F.create_map([F.lit(x) for par in excepciones.items() for x in par])
    
    return F.coalesce(mapa.getItem(col), col)
