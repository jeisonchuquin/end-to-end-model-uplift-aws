'''
Arranque dual de Spark: 
    Usa GlueContext si el job corre en AWS Glue, detecta el paquete awsglue,
    o una SparkSession local (findspark) en desarrollo.
'''

import os
import sys
from pyspark.sql import SparkSession

try:

    from awsglue.context import GlueContext
    from awsglue.job import Job
    from awsglue.utils import getResolvedOptions
    from pyspark.context import SparkContext

    EN_GLUE = True

except ImportError:
    
    EN_GLUE = False




def get_spark_y_args(nombre_app: str, nombres_argumentos: list, defaults_locales: dict):
    '''
    Devuelve (spark, args_dict, job_o_none).

    Params:
        nombres_argumentos: lista de nombres de argumento esperados (sin el `--`), ej. ['input_path', 'output_path'].
        defaults_locales: valores a usar cuando se corre localmente (fuera de Glue).
    '''
    
    if EN_GLUE:
        args = getResolvedOptions(sys.argv, ["JOB_NAME"] + nombres_argumentos)
        sc = SparkContext()
        glue_context = GlueContext(sc)
        spark = glue_context.spark_session
        job = Job(glue_context)
        job.init(args["JOB_NAME"], args)
        spark.conf.set("spark.sql.session.timeZone", "UTC")
        return spark, args, job

    import findspark

    findspark.init()
    spark = (
        SparkSession.builder
        .appName(nombre_app)
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    
    return spark, dict(defaults_locales), None


def base_local() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..")).replace("\\", "/")
