# Rol de ejecución para los Glue Jobs (estandarización y enriquecimiento).
# Acceso de mínimo privilegio: solo al bucket del proyecto, más el rol
# administrado de Glue para logs/metadata del propio servicio.

data "aws_iam_policy_document" "glue_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "glue_etl_role" {
  name               = "${var.project_name}-glue-etl-role"
  assume_role_policy = data.aws_iam_policy_document.glue_assume_role.json
}

resource "aws_iam_role_policy_attachment" "glue_service_role" {
  role       = aws_iam_role.glue_etl_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

data "aws_iam_policy_document" "glue_s3_access" {
  statement {
    sid    = "ListBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
    ]
    resources = [aws_s3_bucket.data_lake.arn]
  }

  statement {
    sid    = "ReadWriteDataZones"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/data/raw/*",
      "${aws_s3_bucket.data_lake.arn}/data/processed/*",
      "${aws_s3_bucket.data_lake.arn}/data/quarantine/*",
      "${aws_s3_bucket.data_lake.arn}/data/curated/*",
    ]
  }

  statement {
    sid       = "ReadScripts"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/scripts/*"]
  }

  statement {
    sid       = "TempDir"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/tmp/*"]
  }
}

resource "aws_iam_role_policy" "glue_s3_access" {
  name   = "${var.project_name}-glue-s3-access"
  role   = aws_iam_role.glue_etl_role.id
  policy = data.aws_iam_policy_document.glue_s3_access.json
}
