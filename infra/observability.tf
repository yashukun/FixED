# ---------------------------------------------------------------------------
# Alarms -> SNS. (Per-service CloudWatch log groups are created by the
# ecs-service module. Container Insights is enabled on the cluster.)
#
# NOTE: worker autoscaling uses CPU target-tracking (in the module). For
# queue-depth-driven scaling, publish a custom CloudWatch metric for the Redis
# Celery list length (LLEN) and add a step-scaling policy — tracked as a
# follow-up; CPU scaling is the sensible default to start.
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alarms" {
  name = "${local.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ---- ALB 5xx (target errors) ----
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name}-alb-target-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = aws_lb.this.arn_suffix }
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# ---- RDS ----
resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name}-rds-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  dimensions          = { DBInstanceIdentifier = aws_db_instance.this.identifier }
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "${local.name}-rds-connections"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  # Catches the pooled-connections-held-during-LLM-calls risk before it saturates.
  threshold     = local.is_prod ? 150 : 60
  dimensions    = { DBInstanceIdentifier = aws_db_instance.this.identifier }
  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  alarm_name          = "${local.name}-rds-free-storage"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 5 * 1024 * 1024 * 1024 # 5 GiB
  dimensions          = { DBInstanceIdentifier = aws_db_instance.this.identifier }
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

# ---- ElastiCache ----
resource "aws_cloudwatch_metric_alarm" "redis_cpu" {
  alarm_name          = "${local.name}-redis-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "EngineCPUUtilization"
  namespace           = "AWS/ElastiCache"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  dimensions          = { ReplicationGroupId = aws_elasticache_replication_group.this.id }
  alarm_actions       = [aws_sns_topic.alarms.arn]
}
