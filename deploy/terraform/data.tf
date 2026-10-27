# One key for the database, secrets and logs, and one key per hospital that wraps that hospital's data keys
# (CTA_KEYRING): deleting a hospital's key crypto-shreds its documents.
resource "aws_kms_key" "platform" {
  description         = "cta ${var.environment}: database, secrets, logs"
  enable_key_rotation = true
  policy              = data.aws_iam_policy_document.kms_platform.json
}

resource "aws_kms_key" "tenant" {
  for_each                = toset(var.tenants)
  description             = "cta ${var.environment}: data keys of ${each.key}"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "kms_platform" {
  statement {
    sid       = "account"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
  statement {
    sid       = "logs"
    actions   = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.region}.amazonaws.com"]
    }
  }
}

resource "aws_db_subnet_group" "main" {
  name       = "cta-${var.environment}"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier                          = "cta-${var.environment}"
  engine                              = "postgres"
  engine_version                      = "16.6"
  instance_class                      = var.db_instance_class
  allocated_storage                   = 50
  max_allocated_storage               = 200
  db_name                             = "cta"
  username                            = "cta_owner"
  manage_master_user_password         = true
  master_user_secret_kms_key_id       = aws_kms_key.platform.arn
  storage_encrypted                   = true
  kms_key_id                          = aws_kms_key.platform.arn
  db_subnet_group_name                = aws_db_subnet_group.main.name
  vpc_security_group_ids              = [aws_security_group.db.id]
  multi_az                            = true
  backup_retention_period             = 14
  deletion_protection                 = true
  iam_database_authentication_enabled = true
  performance_insights_enabled        = true
  performance_insights_kms_key_id     = aws_kms_key.platform.arn
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "cta-${var.environment}-final"
}

resource "aws_secretsmanager_secret" "app" {
  for_each   = toset(["keyring", "gateway-seal-key", "gateway-surrogate-key", "gateway-service-token", "database-url"])
  name       = "cta/${var.environment}/${each.key}"
  kms_key_id = aws_kms_key.platform.arn
}

resource "aws_cloudwatch_log_group" "app" {
  for_each          = toset(["agent", "gateway"])
  name              = "/cta/${var.environment}/${each.key}"
  retention_in_days = 90
  kms_key_id        = aws_kms_key.platform.arn
}
