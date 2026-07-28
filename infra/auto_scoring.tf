# Re-puntúa uplift automáticamente cuando terminan de llegar datos raw nuevos,
# SIN reentrenar. El pipeline de Glue (glue_workflow.tf) ya recomputa processed/
# curated *completos* desde raw/ en cada corrida (mode("overwrite") en los 2
# Jobs), eso ya resuelve "cliente nuevo se agrega, cliente existente se
# actualiza" para processed/curated. Las predicciones de DynamoDB, que sirve el Lambda de la API, 
# reflejan ese mismo refresh sin esperar a un reentrenamiento manual
# solo re-aplicar el modelo ya entrenado (`models/uplift/`) sobre el
# curated/cliente_360 recién actualizado.

resource "aws_s3_object" "run_score_uplift_job_script" {
  bucket = aws_s3_bucket.data_lake.id
  key    = "scripts/uplift-scoring/run_score_uplift_job.sh"
  source = "${path.module}/../src/sagemaker/run_score_uplift_job.sh"
  etag   = filemd5("${path.module}/../src/sagemaker/run_score_uplift_job.sh")
}

resource "aws_s3_object" "score_uplift_script" {
  bucket = aws_s3_bucket.data_lake.id
  key    = "scripts/uplift-scoring/src/sagemaker/score_uplift.py"
  source = "${path.module}/../src/sagemaker/score_uplift.py"
  etag   = filemd5("${path.module}/../src/sagemaker/score_uplift.py")
}

resource "aws_s3_object" "score_uplift_container_requirements" {
  bucket = aws_s3_bucket.data_lake.id
  key    = "scripts/uplift-scoring/src/sagemaker/requirements-uplift-container.txt"
  source = "${path.module}/../src/sagemaker/requirements-uplift-container.txt"
  etag   = filemd5("${path.module}/../src/sagemaker/requirements-uplift-container.txt")
}

locals {
  # Registry de las imágenes built-in de SageMaker (SKLearn)
  sagemaker_sklearn_registry_por_region = {
    "us-east-1" = "683313688378"
  }
  sagemaker_sklearn_image = "${local.sagemaker_sklearn_registry_por_region[var.aws_region]}.dkr.ecr.${var.aws_region}.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3"
}

data "archive_file" "lanzar_scoring_uplift_lambda" {
  type        = "zip"
  output_path = "${path.module}/build/lanzar_scoring_uplift_lambda.zip"

  source {
    filename = "index.py"
    content  = <<-PYEOF
      import os
      import time

      import boto3

      sagemaker = boto3.client("sagemaker")

      BUCKET = os.environ["BUCKET"]
      ROLE_ARN = os.environ["SAGEMAKER_ROLE_ARN"]
      DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
      REGION = os.environ["AWS_REGION_NAME"]
      IMAGE_URI = os.environ["IMAGE_URI"]

      CODE_PREFIX = f"s3://{BUCKET}/scripts/uplift-scoring"


      def _s3_input(name, uri, local_path):
          return {
              "InputName": name,
              "S3Input": {
                  "S3Uri": uri,
                  "LocalPath": local_path,
                  "S3DataType": "S3Prefix",
                  "S3InputMode": "File",
                  "S3DataDistributionType": "FullyReplicated",
              },
          }


      def handler(event, context):
          fecha = time.strftime("%Y-%m-%d")
          job_name = f"peigo-uplift-scoring-auto-{int(time.time())}"

          sagemaker.create_processing_job(
              ProcessingJobName=job_name,
              RoleArn=ROLE_ARN,
              AppSpecification={
                  "ImageUri": IMAGE_URI,
                  "ContainerEntrypoint": ["/bin/bash", "/opt/ml/processing/input/code/run_score_uplift_job.sh"],
              },
              ProcessingResources={
                  "ClusterConfig": {"InstanceCount": 1, "InstanceType": "ml.m5.xlarge", "VolumeSizeInGB": 30},
              },
              Environment={"AWS_REGION": REGION, "DYNAMODB_TABLE": DYNAMODB_TABLE},
              ProcessingInputs=[
                  _s3_input("code", f"{CODE_PREFIX}/run_score_uplift_job.sh", "/opt/ml/processing/input/code"),
                  _s3_input("src", f"{CODE_PREFIX}/src", "/opt/ml/processing/code_extra/src"),
                  _s3_input("cliente_360", f"s3://{BUCKET}/data/curated/cliente_360", "/opt/ml/processing/input/cliente_360"),
                  _s3_input("modelo", f"s3://{BUCKET}/models/uplift/", "/opt/ml/processing/input/modelo"),
              ],
              ProcessingOutputConfig={
                  "Outputs": [{
                      "OutputName": "predicciones",
                      "S3Output": {
                          "S3Uri": f"s3://{BUCKET}/data/predictions/uplift_scores/dt={fecha}/",
                          "LocalPath": "/opt/ml/processing/output/predictions",
                          "S3UploadMode": "EndOfJob",
                      },
                  }],
              },
          )
          
          print(f"Processing Job de scoring lanzado: {job_name}")
          return {"job_name": job_name}
    PYEOF
  }
}

data "aws_iam_policy_document" "lanzar_scoring_uplift_permisos" {
  statement {
    sid       = "LaunchScoringProcessingJob"
    effect    = "Allow"
    actions   = ["sagemaker:CreateProcessingJob"]
    resources = ["*"] # el ARN del job no existe aún al momento de crearlo -- práctica estándar de SageMaker.
  }
  statement {
    sid       = "PassSageMakerExecutionRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.sagemaker_execution_role.arn]
  }
}

resource "aws_iam_role" "lanzar_scoring_uplift_lambda_role" {
  name               = "${var.project_name}-lanzar-scoring-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "lanzar_scoring_uplift_basic_execution" {
  role       = aws_iam_role.lanzar_scoring_uplift_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lanzar_scoring_uplift_permisos" {
  name   = "${var.project_name}-lanzar-scoring-permisos"
  role   = aws_iam_role.lanzar_scoring_uplift_lambda_role.id
  policy = data.aws_iam_policy_document.lanzar_scoring_uplift_permisos.json
}

resource "aws_lambda_function" "lanzar_scoring_uplift" {
  function_name    = "${var.project_name}-lanzar-scoring-uplift"
  role             = aws_iam_role.lanzar_scoring_uplift_lambda_role.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  timeout          = 30
  filename         = data.archive_file.lanzar_scoring_uplift_lambda.output_path
  source_code_hash = data.archive_file.lanzar_scoring_uplift_lambda.output_base64sha256

  environment {
    variables = {
      BUCKET             = aws_s3_bucket.data_lake.id
      SAGEMAKER_ROLE_ARN = aws_iam_role.sagemaker_execution_role.arn
      DYNAMODB_TABLE     = aws_dynamodb_table.uplift_scores.name
      AWS_REGION_NAME    = var.aws_region # Lambda reserva "AWS_REGION" como variable de entorno del runtime, no se puede sobreescribir
      IMAGE_URI          = local.sagemaker_sklearn_image
    }
  }
}

resource "aws_cloudwatch_event_rule" "curated_ready" {
  name        = "${var.project_name}-curated-ready"
  description = "Dispara el re-scoring de uplift (sin reentrenar) cuando el crawler de curated termina OK."

  event_pattern = jsonencode({
    source      = ["aws.glue"]
    detail-type = ["Glue Crawler State Change"]
    detail = {
      crawlerName = [aws_glue_crawler.curated.name]
      state       = ["Succeeded"]
    }
  })
}

resource "aws_cloudwatch_event_target" "trigger_scoring" {
  rule      = aws_cloudwatch_event_rule.curated_ready.name
  target_id = "trigger-uplift-scoring-lambda"
  arn       = aws_lambda_function.lanzar_scoring_uplift.arn
}

resource "aws_lambda_permission" "allow_eventbridge_scoring" {
  statement_id  = "AllowExecutionFromEventBridgeCuratedReady"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lanzar_scoring_uplift.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.curated_ready.arn
}
