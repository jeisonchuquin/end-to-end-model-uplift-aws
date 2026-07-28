# Sube los scripts de los Glue Jobs y el paquete utils/ (--extra-py-files) a S3,
# y define los 2 Glue Jobs.

resource "aws_s3_object" "standardize_script" {
  bucket = aws_s3_bucket.data_lake.id
  key    = "scripts/01_standarize.py"
  source = "${path.module}/../src/glue_jobs/01_standarize.py"
  etag   = filemd5("${path.module}/../src/glue_jobs/01_standarize.py")
}

resource "aws_s3_object" "enrich_curated_script" {
  bucket = aws_s3_bucket.data_lake.id
  key    = "scripts/02_enrich_curated.py"
  source = "${path.module}/../src/glue_jobs/02_enrich_curated.py"
  etag   = filemd5("${path.module}/../src/glue_jobs/02_enrich_curated.py")
}

# zip explícito preservando la carpeta utils/
data "archive_file" "utils_zip" {
  type        = "zip"
  output_path = "${path.module}/build/utils.zip"

  source {
    content  = file("${path.module}/../utils/normalizacion.py")
    filename = "utils/normalizacion.py"
  }
  source {
    content  = file("${path.module}/../utils/fechas.py")
    filename = "utils/fechas.py"
  }
  source {
    content  = file("${path.module}/../utils/spark_boot.py")
    filename = "utils/spark_boot.py"
  }
  source {
    content  = file("${path.module}/../utils/__init__.py")
    filename = "utils/__init__.py"
  }
}

resource "aws_s3_object" "utils_zip" {
  bucket = aws_s3_bucket.data_lake.id
  key    = "scripts/dependencies/utils.zip"
  source = data.archive_file.utils_zip.output_path
  etag   = data.archive_file.utils_zip.output_md5
}

locals {
  glue_common_args = {
    "--extra-py-files"                   = "s3://${aws_s3_bucket.data_lake.id}/${aws_s3_object.utils_zip.key}"
    "--TempDir"                          = "s3://${aws_s3_bucket.data_lake.id}/tmp/"
    "--enable-continuous-cloudwatch-log" = "true"
    "--job-language"                     = "python"
  }
}

resource "aws_glue_job" "standardize" {
  name              = "${var.project_name}-standardize"
  role_arn          = aws_iam_role.glue_etl_role.arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 30
  max_retries       = 0

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.data_lake.id}/${aws_s3_object.standardize_script.key}"
    python_version  = "3"
  }

  default_arguments = merge(local.glue_common_args, {
    "--input_path"      = "s3://${aws_s3_bucket.data_lake.id}/data/raw"
    "--output_path"     = "s3://${aws_s3_bucket.data_lake.id}/data/processed"
    "--quarantine_path" = "s3://${aws_s3_bucket.data_lake.id}/data/quarantine"
  })
}

resource "aws_glue_job" "enrich_curated" {
  name              = "${var.project_name}-enrich-curated"
  role_arn          = aws_iam_role.glue_etl_role.arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 30
  max_retries       = 0

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.data_lake.id}/${aws_s3_object.enrich_curated_script.key}"
    python_version  = "3"
  }

  default_arguments = merge(local.glue_common_args, {
    "--input_path"  = "s3://${aws_s3_bucket.data_lake.id}/data/processed"
    "--output_path" = "s3://${aws_s3_bucket.data_lake.id}/data/curated"
  })
}
