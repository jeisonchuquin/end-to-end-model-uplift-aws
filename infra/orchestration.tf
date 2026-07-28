# Dispara el Glue Workflow completo cuando llega un archivo nuevo a data/raw/.
#
# El único código custom en toda la orquestación es este Lambda de ~10 líneas
# (solo llama glue:StartWorkflowRun) -- todo el encadenado real (crawler -> job ->
# crawler -> job -> crawler) vive en los aws_glue_trigger de glue_workflow.tf,
# nativos de Glue, sin Step Functions ni lógica propia de control de flujo.
#
# S3 (EventBridge habilitado) --Object Created en data/raw/--> EventBridge rule --> Lambda (start_workflow_run) --> Glue Workflow

resource "aws_s3_bucket_notification" "eventbridge" {
  bucket      = aws_s3_bucket.data_lake.id
  eventbridge = true
}

data "archive_file" "trigger_workflow_lambda" {
  type        = "zip"
  output_path = "${path.module}/build/trigger_workflow_lambda.zip"

  source {
    filename = "index.py"
    content  = <<-PYEOF
      import os
      import boto3

      glue = boto3.client("glue")

      def handler(event, context):
          workflow_name = os.environ["WORKFLOW_NAME"]
          respuesta = glue.start_workflow_run(Name=workflow_name)
          print(f"Workflow '{workflow_name}' iniciado, run_id={respuesta['RunId']}")
          return {"workflow_name": workflow_name, "run_id": respuesta["RunId"]}
    PYEOF
  }
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "trigger_workflow_lambda_role" {
  name               = "${var.project_name}-trigger-workflow-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.trigger_workflow_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda_start_workflow" {
  statement {
    effect  = "Allow"
    actions = ["glue:StartWorkflowRun"]
    resources = [
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workflow/${aws_glue_workflow.pipeline.name}"
    ]
  }
}

resource "aws_iam_role_policy" "lambda_start_workflow" {
  name   = "${var.project_name}-lambda-start-workflow"
  role   = aws_iam_role.trigger_workflow_lambda_role.id
  policy = data.aws_iam_policy_document.lambda_start_workflow.json
}

resource "aws_lambda_function" "trigger_workflow" {
  function_name    = "${var.project_name}-trigger-workflow"
  role             = aws_iam_role.trigger_workflow_lambda_role.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  timeout          = 15
  filename         = data.archive_file.trigger_workflow_lambda.output_path
  source_code_hash = data.archive_file.trigger_workflow_lambda.output_base64sha256

  environment {
    variables = {
      WORKFLOW_NAME = aws_glue_workflow.pipeline.name
    }
  }
}

resource "aws_cloudwatch_event_rule" "raw_object_created" {
  name        = "${var.project_name}-raw-object-created"
  description = "Dispara el pipeline completo cuando se sube un archivo nuevo a data/raw/"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.data_lake.id] }
      object = { key = [{ prefix = "data/raw/" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "trigger_workflow" {
  rule      = aws_cloudwatch_event_rule.raw_object_created.name
  target_id = "trigger-glue-workflow-lambda"
  arn       = aws_lambda_function.trigger_workflow.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.trigger_workflow.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.raw_object_created.arn
}
