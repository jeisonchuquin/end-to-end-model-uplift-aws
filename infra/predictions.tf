# Glue predicciones con schema EXPLÍCITO en Terraform: el
# schema lo controla el propio script de scoring, evita depender de que un crawler 
# corra después de cada scoring batch antes de que la tabla quede consultable.
# escribe en S3 y DynamoDB

resource "aws_glue_catalog_database" "predictions" {
  name        = "${local.project_slug}_predictions"
  description = "Resultados de modelos listos para consumo (scores, segmentos)"
}

resource "aws_glue_catalog_table" "uplift_scores" {
  name          = "uplift_scores"
  database_name = aws_glue_catalog_database.predictions.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification" = "parquet"
    "typeOfData"     = "file"
    # Partition projection: Athena calcula solas las particiones dt= existentes en
    # vez de necesitar MSCK REPAIR TABLE / BatchCreatePartition después de cada
    # corrida de scoring -- el scoring job solo escribe el parquet, nada más.
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.range"         = "2026-01-01,NOW"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "storage.location.template"   = "s3://${aws_s3_bucket.data_lake.id}/data/predictions/uplift_scores/dt=$${dt}/"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.data_lake.id}/data/predictions/uplift_scores/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "cliente_id"
      type = "string"
    }
    columns {
      name    = "score_uplift"
      type    = "double"
      comment = "tau estimado: P(aumento_uso | tratamiento, X) - P(aumento_uso | control, X)"
    }
    columns {
      name    = "p_tratamiento"
      type    = "double"
      comment = "P(aumento_uso | X) según el modelo del brazo tratamiento (T-learner)"
    }
    columns {
      name    = "p_control"
      type    = "double"
      comment = "P(aumento_uso | X) según el modelo del brazo control (T-learner)"
    }
    columns {
      name    = "segmento_uplift"
      type    = "string"
      comment = "persuadible | sure_thing | lost_cause | sleeping_dog (ver score_uplift.py)"
    }
    columns {
      name = "razones_principales"
      type = "string"
    }
    columns {
      name = "version_modelo"
      type = "string"
    }
  }

  partition_keys {
    name    = "dt"
    type    = "string"
    comment = "fecha de la corrida de scoring (YYYY-MM-DD), particiona igual que models/scores/dt=.../ en la capa de propensión"
  }
}

# El mismo rol de SageMaker (entrena y puntúa el T-learner) necesita escribir en la
# nueva zona predictions/.
data "aws_iam_policy_document" "sagemaker_predictions_write" {
  statement {
    sid       = "WritePredictions"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/data/predictions/*"]
  }
}

resource "aws_iam_role_policy" "sagemaker_predictions_write" {
  name   = "${var.project_name}-sagemaker-predictions-write"
  role   = aws_iam_role.sagemaker_execution_role.id
  policy = data.aws_iam_policy_document.sagemaker_predictions_write.json
}

# --- DynamoDB: capa de serving de baja latencia (ver comentario de cabecera) ---

resource "aws_dynamodb_table" "uplift_scores" {
  name         = "${var.project_name}-uplift-scores"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "cliente_id"

  attribute {
    name = "cliente_id"
    type = "S"
  }

  tags = {
    Proposito = "Serving de baja latencia para el Lambda de consulta de uplift -- la tabla Glue/S3 sigue siendo la fuente de auditoría"
  }
}

# score_uplift.py (bajo el rol de SageMaker) escribe en DynamoDB además de S3.
data "aws_iam_policy_document" "sagemaker_dynamodb_write" {
  statement {
    sid       = "WriteUpliftScoresDynamo"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem", "dynamodb:BatchWriteItem"]
    resources = [aws_dynamodb_table.uplift_scores.arn]
  }
}

resource "aws_iam_role_policy" "sagemaker_dynamodb_write" {
  name   = "${var.project_name}-sagemaker-dynamodb-write"
  role   = aws_iam_role.sagemaker_execution_role.id
  policy = data.aws_iam_policy_document.sagemaker_dynamodb_write.json
}
