# ── CloudWatch Log Group ──────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name_prefix}"
  retention_in_days = 30
  tags              = { Name = "${local.name_prefix}-logs" }
}

# ── CloudWatch Alarms ─────────────────────────────────────────────────────────

# High 5xx error rate from ALB
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name_prefix}-alb-5xx-high"
  alarm_description   = "ALB 5xx error rate exceeded 5% for 5 minutes."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }

  alarm_actions = compact([try(aws_sns_topic.alerts.arn, "")])
  ok_actions    = compact([try(aws_sns_topic.alerts.arn, "")])
}

# High task CPU utilisation
resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  alarm_name          = "${local.name_prefix}-ecs-cpu-high"
  alarm_description   = "ECS average CPU utilisation exceeded 80%."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.app.name
  }

  alarm_actions = compact([try(aws_sns_topic.alerts.arn, "")])
}

# High task memory utilisation
resource "aws_cloudwatch_metric_alarm" "ecs_memory_high" {
  alarm_name          = "${local.name_prefix}-ecs-memory-high"
  alarm_description   = "ECS average memory utilisation exceeded 80%."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.app.name
  }

  alarm_actions = compact([try(aws_sns_topic.alerts.arn, "")])
}

# ALB response time P99
resource "aws_cloudwatch_metric_alarm" "alb_latency" {
  alarm_name          = "${local.name_prefix}-alb-p99-latency"
  alarm_description   = "ALB P99 response time exceeded 5 seconds."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p99"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }

  alarm_actions = compact([try(aws_sns_topic.alerts.arn, "")])
}

# ── SNS Topic for alerts ─────────────────────────────────────────────────────

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
  tags = { Name = "${local.name_prefix}-alerts" }
}

# ── CloudWatch Dashboard ──────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name_prefix}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "ALB Request Count & 5xx Errors"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.main.arn_suffix],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", aws_lb.main.arn_suffix]
          ]
          view = "timeSeries"
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "ALB P50 / P99 Latency (s)"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix, { stat = "p50", label = "p50" }],
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix, { stat = "p99", label = "p99" }]
          ]
          view = "timeSeries"
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "ECS CPU & Memory Utilisation (%)"
          period = 60
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.app.name],
            ["AWS/ECS", "MemoryUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.app.name]
          ]
          view = "timeSeries"
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "ECS Running Task Count"
          period = 60
          metrics = [
            ["ECS/ContainerInsights", "RunningTaskCount", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.app.name]
          ]
          view = "timeSeries"
        }
      }
    ]
  })
}
