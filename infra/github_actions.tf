# Identidad OIDC para GitHub Actions

variable "github_repo" {
  description = "Repositorio de GitHub autorizado a asumir el rol de CI (formato owner/repo)."
  type        = string
  default     = "jeisonchuquin/end-to-end-model-uplift-aws"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  thumbprint_list = [
    "ab9d0263244dd0326eb67015705a667e79cfe998",
  ]
}

data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${var.project_name}-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
}

data "aws_iam_policy_document" "github_actions_permissions" {
  # Sincronizar los scripts de los Glue Jobs (deploy-glue.yml)
  statement {
    sid       = "SyncGlueScripts"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/scripts/*"]
  }
  statement {
    sid       = "ListBucketForSync"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data_lake.arn]
  }

  # Ejecutar y monitorear el Glue Workflow tras actualizar el código.
  statement {
    sid    = "RunGlueWorkflow"
    effect = "Allow"
    actions = [
      "glue:StartWorkflowRun",
      "glue:GetWorkflowRun",
      "glue:GetWorkflowRuns",
      "glue:GetWorkflow",
    ]
    resources = ["arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workflow/${aws_glue_workflow.pipeline.name}"]
  }
  statement {
    sid    = "ReadGlueJobRuns"
    effect = "Allow"
    actions = [
      "glue:GetJobRun",
      "glue:GetJobRuns",
      "glue:GetCrawler",
    ]
    resources = ["*"]
  }

  # Lanzar y monitorear el entrenamiento/scoring de uplift (train-model.yml).
  statement {
    sid       = "LaunchSageMakerProcessingJobs"
    effect    = "Allow"
    actions   = ["sagemaker:CreateProcessingJob"]
    resources = ["*"]
  }
  statement {
    sid    = "ReadSageMakerProcessingJobs"
    effect = "Allow"
    actions = [
      "sagemaker:DescribeProcessingJob",
      "sagemaker:ListProcessingJobs",
      "sagemaker:AddTags",
    ]
    resources = ["arn:aws:sagemaker:${var.aws_region}:${data.aws_caller_identity.current.account_id}:processing-job/peigo-uplift-*"]
  }
  statement {
    sid       = "PassSageMakerExecutionRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.sagemaker_execution_role.arn]
  }

  # Logs de los Processing Jobs, para diagnosticar un fallo directo desde el run de CI.
  statement {
    sid    = "ReadProcessingJobLogs"
    effect = "Allow"
    actions = [
      "logs:GetLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/sagemaker/ProcessingJobs:*"]
  }
}

resource "aws_iam_role_policy" "github_actions" {
  name   = "${var.project_name}-github-actions-permisos"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_permissions.json
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}
