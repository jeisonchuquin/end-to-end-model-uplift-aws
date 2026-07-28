'''
Corrección de fechas multi-formato.

De acuerdo con el notebook 00_data_standard_valid.ipynb se encontró 3 formatos mezclados en toda
columna de fecha de los 5 archivos: 2023-01-21 (iso), 20/09/2024 (ymd) y 455889600000 (epoch)
'''

from pyspark.sql import Column
from pyspark.sql import functions as F


# Definimos regex para encontrar los tipos de fecha
_RE_EPOCH_MS = r"^\d+$"
_RE_ISO = r"^\d{4}-\d{2}-\d{2}$"
_RE_DDMMYYYY = r"^\d{2}/\d{2}/\d{4}$"


def parsear_fecha_multiformato(col: Column) -> Column:
    '''
    Devuelve una columna `date`. Formatos no reconocidos quedan en NULL
    
    Se distinguen de los nulos originales comparando contra `col.isNotNull()`
    
    Params:
        col: Columna con fechas a corregir
    '''
    c = F.trim(col)

    es_epoch_ms = c.rlike(_RE_EPOCH_MS)
    es_iso = c.rlike(_RE_ISO)
    es_ddmmyyyy = c.rlike(_RE_DDMMYYYY)
    
    fecha_epoch = F.to_date((c.cast("long") / F.lit(1000)).cast("timestamp"))
    fecha_iso = F.to_date(c, "yyyy-MM-dd")
    fecha_ddmmyyyy = F.to_date(c, "dd/MM/yyyy")

    return (
        F.when(es_epoch_ms, fecha_epoch)
        .when(es_iso, fecha_iso)
        .when(es_ddmmyyyy, fecha_ddmmyyyy)
        .otherwise(F.lit(None).cast("date"))
    )
