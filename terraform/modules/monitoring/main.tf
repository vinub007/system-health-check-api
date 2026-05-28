###############################################################################
# Monitoring module – CloudWatch Logs, Dashboards, Alarms, SNS
###############################################################################

variable "name_prefix"              {}
variable "common_tags"              { type = map(string) }
variable "ecs_service_name"         {}
variable "ecs_cluster_name"         {}
variable "alb_arn_suffix"           {}
variable "target_group_arn_suffix"  {}
variable "alarm_email"              { default = "" }

# ── CloudWatch Log Group ─────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.name_prefix}"
  retention_in_days = 30
  tags              = var.common_tags
}

# ── SNS topic for alarms ─────────────────────────────────────────────────────

resource "aws_sns_topic" "alarms" {
  name = "${var.name_prefix}-alarms"
  tags = var.common_tags
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ── CloudWatch Alarms ────────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "${var.name_prefix}-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "ECS service CPU > 80%"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  tags = var.common_tags
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.name_prefix}-alb-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"
  alarm_description   = "ALB receiving >10 5xx responses per minute"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  tags = var.common_tags
}

resource "aws_cloudwatch_metric_alarm" "alb_latency" {
  alarm_name          = "${var.name_prefix}-alb-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "p95"
  threshold           = 5
  alarm_description   = "p95 ALB latency > 5s"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }

  tags = var.common_tags
}

# ── CloudWatch Dashboard ─────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "api" {
  dashboard_name = "${var.name_prefix}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          title  = "ECS CPU Utilization"
          metrics = [["AWS/ECS", "CPUUtilization",
            "ClusterName", var.ecs_cluster_name,
            "ServiceName", var.ecs_service_name]]
          period = 300
          stat   = "Average"
        }
      },
      {
        type = "metric"
        properties = {
          title  = "ALB Request Count"
          metrics = [["AWS/ApplicationELB", "RequestCount",
            "LoadBalancer", var.alb_arn_suffix]]
          period = 60
          stat   = "Sum"
        }
      },
      {
        type = "metric"
        properties = {
          title  = "ALB Target Response Time (p95)"
          metrics = [["AWS/ApplicationELB", "TargetResponseTime",
            "LoadBalancer", var.alb_arn_suffix]]
          period = 60
          stat   = "p95"
        }
      },
      {
        type = "log"
        properties = {
          title   = "Application Errors"
          query   = "SOURCE '${aws_cloudwatch_log_group.api.name}' | filter level = 'ERROR' | stats count(*) by bin(5m)"
          region  = "us-east-1"
          view    = "timeSeries"
        }
      }
    ]
  })
}

output "log_group_name" { value = aws_cloudwatch_log_group.api.name }
output "alarm_topic_arn" { value = aws_sns_topic.alarms.arn }
