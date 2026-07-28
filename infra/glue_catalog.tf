# Arquitectura medallón en el Glue Data Catalog: una base de datos por zona de S3
# raw/processed/quarantine/curated, cada una poblada por su propio Glue Crawler.
# Los crawlers no llevan schedule, se disparan desde el Glue Workflow
# ver glue_workflow.tf, no por cron ni de forma manual.

resource "aws_glue_catalog_database" "raw" {
  name = "${local.project_slug}_raw"
}

resource "aws_glue_catalog_database" "processed" {
  name = "${local.project_slug}_processed"
}

resource "aws_glue_catalog_database" "quarantine" {
  name = "${local.project_slug}_quarantine"
}

resource "aws_glue_catalog_database" "curated" {
  name        = "${local.project_slug}_curated"
  description = "Capa gold lista para consumo (análisis + features del modelo): cliente_360 y piloto_pilot_summary."
}

locals {
  crawler_schema_change_policy = {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }
}

resource "aws_glue_crawler" "raw" {
  name          = "${var.project_name}-raw-crawler"
  role          = aws_iam_role.glue_etl_role.arn
  database_name = aws_glue_catalog_database.raw.name

  s3_target {
    path = "s3://${aws_s3_bucket.data_lake.id}/data/raw/"
  }

  schema_change_policy {
    update_behavior = local.crawler_schema_change_policy.update_behavior
    delete_behavior = local.crawler_schema_change_policy.delete_behavior
  }
}

resource "aws_glue_crawler" "processed" {
  name          = "${var.project_name}-processed-crawler"
  role          = aws_iam_role.glue_etl_role.arn
  database_name = aws_glue_catalog_database.processed.name

  s3_target {
    path = "s3://${aws_s3_bucket.data_lake.id}/data/processed/"
  }

  schema_change_policy {
    update_behavior = local.crawler_schema_change_policy.update_behavior
    delete_behavior = local.crawler_schema_change_policy.delete_behavior
  }
}

resource "aws_glue_crawler" "quarantine" {
  name          = "${var.project_name}-quarantine-crawler"
  role          = aws_iam_role.glue_etl_role.arn
  database_name = aws_glue_catalog_database.quarantine.name

  s3_target {
    path = "s3://${aws_s3_bucket.data_lake.id}/data/quarantine/"
  }

  schema_change_policy {
    update_behavior = local.crawler_schema_change_policy.update_behavior
    delete_behavior = local.crawler_schema_change_policy.delete_behavior
  }
}

resource "aws_glue_crawler" "curated" {
  name          = "${var.project_name}-curated-crawler"
  role          = aws_iam_role.glue_etl_role.arn
  database_name = aws_glue_catalog_database.curated.name

  s3_target {
    path = "s3://${aws_s3_bucket.data_lake.id}/data/curated/"
  }

  schema_change_policy {
    update_behavior = local.crawler_schema_change_policy.update_behavior
    delete_behavior = local.crawler_schema_change_policy.delete_behavior
  }
}
