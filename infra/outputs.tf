output "data_lake_bucket_name" {
  description = "Nombre del bucket S3 usado como data lake del proyecto."
  value       = aws_s3_bucket.data_lake.id
}

output "glue_etl_role_arn" {
  description = "ARN del rol de ejecución para los Glue Jobs."
  value       = aws_iam_role.glue_etl_role.arn
}

output "sagemaker_execution_role_arn" {
  description = "ARN del rol de ejecución para Training Jobs, Model Registry, Endpoint y Batch Transform de SageMaker."
  value       = aws_iam_role.sagemaker_execution_role.arn
}

output "glue_catalog_databases" {
  description = "Bases de datos del Glue Data Catalog, una por zona (arquitectura medallón)."
  value = {
    raw        = aws_glue_catalog_database.raw.name
    processed  = aws_glue_catalog_database.processed.name
    quarantine = aws_glue_catalog_database.quarantine.name
    curated    = aws_glue_catalog_database.curated.name
  }
}

output "glue_workflow_name" {
  description = "Nombre del Glue Workflow que encadena todo el pipeline (crawler raw -> Job1 -> crawlers -> Job2 -> crawler curated)."
  value       = aws_glue_workflow.pipeline.name
}
