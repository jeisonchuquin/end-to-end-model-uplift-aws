# Expone el score/segmento de uplift vía una API HTTP: GET /clientes/{id}/uplift.
# El Lambda lee de DynamoDB (ver predictions.tf)
resource "aws_s3_bucket" "athena_resultados" {
  bucket = "${var.project_name}-athena-resultados-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_lifecycle_configuration" "athena_resultados" {
  bucket = aws_s3_bucket.athena_resultados.id

  rule {
    id     = "expirar-resultados-query"
    status = "Enabled"
    filter {}
    expiration {
      days = 7
    }
  }
}

resource "aws_athena_workgroup" "peigo" {
  name = "${var.project_name}-workgroup"

  configuration {
    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_resultados.id}/"
    }
  }
}

data "aws_iam_policy_document" "lambda_consultar_uplift_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_consultar_uplift_role" {
  name               = "${var.project_name}-consultar-uplift-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_consultar_uplift_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_consultar_uplift_basic" {
  role       = aws_iam_role.lambda_consultar_uplift_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda_consultar_uplift_permisos" {
  statement {
    sid       = "ReadUpliftScoresDynamo"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.uplift_scores.arn]
  }
}

resource "aws_iam_role_policy" "lambda_consultar_uplift_permisos" {
  name   = "${var.project_name}-consultar-uplift-permisos"
  role   = aws_iam_role.lambda_consultar_uplift_role.id
  policy = data.aws_iam_policy_document.lambda_consultar_uplift_permisos.json
}

data "archive_file" "consultar_uplift_lambda" {
  type        = "zip"
  source_file = "${path.module}/../src/lambda/consultar_uplift/handler.py"
  output_path = "${path.module}/build/consultar_uplift.zip"
}

resource "aws_lambda_function" "consultar_uplift" {
  function_name    = "${var.project_name}-consultar-uplift"
  role             = aws_iam_role.lambda_consultar_uplift_role.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = 20
  memory_size      = 256
  filename         = data.archive_file.consultar_uplift_lambda.output_path
  source_code_hash = data.archive_file.consultar_uplift_lambda.output_base64sha256

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.uplift_scores.name
    }
  }
}

resource "aws_apigatewayv2_api" "uplift_api" {
  name          = "${var.project_name}-uplift-api"
  protocol_type = "HTTP"
  description   = "Consulta puntual del score/segmento de uplift por cliente_id"
}

resource "aws_apigatewayv2_integration" "consultar_uplift" {
  api_id                 = aws_apigatewayv2_api.uplift_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.consultar_uplift.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "consultar_uplift" {
  api_id    = aws_apigatewayv2_api.uplift_api.id
  route_key = "GET /clientes/{cliente_id}/uplift"
  target    = "integrations/${aws_apigatewayv2_integration.consultar_uplift.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.uplift_api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_apigateway" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.consultar_uplift.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.uplift_api.execution_arn}/*/*"
}

output "uplift_api_endpoint" {
  description = "URL base de la API -- GET {url}/clientes/{cliente_id}/uplift"
  value       = aws_apigatewayv2_api.uplift_api.api_endpoint
}
