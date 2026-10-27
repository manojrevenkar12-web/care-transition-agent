output "console_dns" { value = aws_lb.console.dns_name }
output "database_endpoint" { value = aws_db_instance.main.address }
output "tenant_keys" { value = { for t, k in aws_kms_key.tenant : t => k.arn } }
