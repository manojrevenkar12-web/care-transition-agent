resource "aws_ecs_cluster" "main" {
  name = "cta-${var.environment}"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "cta.internal"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "gateway" {
  name = "gateway"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}

locals {
  secret = { for k, v in aws_secretsmanager_secret.app : k => v.arn }
}

resource "aws_ecs_task_definition" "gateway" {
  family                   = "cta-gateway"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.gateway.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }
  container_definitions = jsonencode([{
    name                   = "gateway"
    image                  = var.gateway_image
    essential              = true
    readonlyRootFilesystem = true
    portMappings           = [{ containerPort = 8070 }]
    environment            = [{ name = "CTA_GATEWAY_LISTEN", value = "0.0.0.0:8070" }, { name = "AWS_REGION", value = var.region }]
    secrets = [
      { name = "CTA_GATEWAY_SEAL_KEY", valueFrom = local.secret["gateway-seal-key"] },
      { name = "CTA_GATEWAY_SURROGATE_KEY", valueFrom = local.secret["gateway-surrogate-key"] },
      { name = "CTA_GATEWAY_SERVICE_TOKENS", valueFrom = local.secret["gateway-service-token"] },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options   = { awslogs-group = aws_cloudwatch_log_group.app["gateway"].name, awslogs-region = var.region, awslogs-stream-prefix = "gateway" }
    }
  }])
}

resource "aws_ecs_task_definition" "agent" {
  family                   = "cta-agent"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.agent.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }
  container_definitions = jsonencode([{
    name         = "agent"
    image        = var.agent_image
    essential    = true
    portMappings = [{ containerPort = 8000 }]
    environment = [
      { name = "CTA_GATEWAY_URL", value = "http://gateway.cta.internal:8070" },
      { name = "OTEL_SERVICE_NAME", value = "cta-agent" },
    ]
    secrets = [
      { name = "CTA_KEYRING", valueFrom = local.secret["keyring"] },
      { name = "CTA_GATEWAY_TOKEN", valueFrom = local.secret["gateway-service-token"] },
      { name = "CTA_DATABASE_URL", valueFrom = local.secret["database-url"] },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options   = { awslogs-group = aws_cloudwatch_log_group.app["agent"].name, awslogs-region = var.region, awslogs-stream-prefix = "agent" }
    }
  }])
}

resource "aws_ecs_service" "gateway" {
  name            = "gateway"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.gateway.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.gateway.id]
  }
  service_registries { registry_arn = aws_service_discovery_service.gateway.arn }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

resource "aws_ecs_service" "agent" {
  name            = "agent"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.agent.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.agent.id]
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.agent.arn
    container_name   = "agent"
    container_port   = 8000
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

resource "aws_lb" "console" {
  name                       = "cta-${var.environment}"
  load_balancer_type         = "application"
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "agent" {
  name        = "cta-agent-${var.environment}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"
  health_check { path = "/readyz" }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.console.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.agent.arn
  }
}
