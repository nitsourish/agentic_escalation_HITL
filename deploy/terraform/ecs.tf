# ── ECS Cluster ───────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Name = "${local.name_prefix}-cluster" }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = var.desired_count
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# ── Task Definition ───────────────────────────────────────────────────────────

resource "aws_ecs_task_definition" "app" {
  family                   = "${local.name_prefix}-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "escalation-api"
      image     = "${aws_ecr_repository.app.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "LLM_PROVIDER",              value = var.llm_provider },
        { name = "LLM_CONFIDENCE_THRESHOLD",  value = var.llm_confidence_threshold },
        { name = "SKIP_NLI",                  value = var.skip_nli },
        { name = "PORT",                       value = tostring(var.container_port) },
        { name = "WORKERS",                    value = "2" }
      ]

      # Secrets injected at task launch — never appear in plaintext env vars.
      secrets = [
        {
          name      = "OPENAI_API_KEY"
          valueFrom = aws_secretsmanager_secret.openai_api_key.arn
        },
        {
          name      = "GEMINI_API_KEY"
          valueFrom = aws_secretsmanager_secret.gemini_api_key.arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -sf http://localhost:${var.container_port}/health || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 60
      }

      # Soft / hard memory limits
      memoryReservation = var.task_memory / 2
    }
  ])

  tags = { Name = "${local.name_prefix}-task" }
}

# ── ECS Service ───────────────────────────────────────────────────────────────

resource "aws_ecs_service" "app" {
  name                               = "${local.name_prefix}-service"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.app.arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  health_check_grace_period_seconds  = 90
  enable_execute_command             = true

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "escalation-api"
    container_port   = var.container_port
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [
    aws_lb_listener.http,
    aws_iam_role_policy_attachment.ecs_execution_managed,
  ]

  tags = { Name = "${local.name_prefix}-service" }

  lifecycle {
    # Allow external deployments (e.g., CI/CD) to change the task definition
    # without Terraform reverting to the pinned version.
    ignore_changes = [task_definition, desired_count]
  }
}
