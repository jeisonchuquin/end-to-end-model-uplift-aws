# Rol de ejecución para SageMaker: Training Jobs, Model Registry, Endpoint
# serverless y Batch Transform Job (todos usan el mismo rol, ver sección 6 del
# plan). Se apoya en la policy administrada de SageMaker para las acciones
# propias del servicio (crear jobs, endpoints, etc.) + una policy propia
# scopeada al bucket del proyecto para leer curated/ y escribir models/.

data "aws_iam_policy_document" "sagemaker_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker_execution_role" {
  name               = "${var.project_name}-sagemaker-role"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume_role.json
}

resource "aws_iam_role_policy_attachment" "sagemaker_full_access" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

data "aws_iam_policy_document" "sagemaker_s3_access" {
  statement {
    sid    = "ListBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
    ]
    resources = [aws_s3_bucket.data_lake.arn]
  }

  statement {
    sid    = "ReadCuratedWriteModels"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/data/curated/*",
      "${aws_s3_bucket.data_lake.arn}/models/*",
    ]
  }

  statement {
    # Solo lectura: train_uplift.py necesita processed/transacciones para construir
    # el panel tratado/control (fecha de corte común) -- ver src/sagemaker/train_uplift.py.
    sid       = "ReadProcessed"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/data/processed/*"]
  }

  statement {
    # Los Processing Jobs lanzados por launch_uplift_processing_job.py/
    # launch_score_uplift_processing_job.py suben su propio código al bucket
    # default de SageMaker (fuera de este bucket, cubierto por
    # AmazonSageMakerFullAccess) -- pero el de auto_scoring.tf (Lambda
    # disparado por el crawler de curated, sin el SDK) lee el código desde una
    # ruta fija DENTRO de este bucket (scripts/uplift-scoring/), así que el rol
    # necesita permiso explícito ahí. Encontrado corriendo el trigger real:
    # AccessDenied en s3:GetObject sobre scripts/uplift-scoring/....
    sid       = "ReadScripts"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/scripts/*"]
  }
}

resource "aws_iam_role_policy" "sagemaker_s3_access" {
  name   = "${var.project_name}-sagemaker-s3-access"
  role   = aws_iam_role.sagemaker_execution_role.id
  policy = data.aws_iam_policy_document.sagemaker_s3_access.json
}
