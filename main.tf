data "aws_caller_identity" "current" {}

data "archive_file" "lambda" {
  type        = "zip"
  source_file = "${path.module}/lambda/remediate.py"
  output_path = "${path.module}/remediator.zip"
}

locals {
  instance_arn = "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/${var.monitored_instance_id}"
}

resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.notification_email == null ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

resource "aws_dynamodb_table" "events" {
  name         = "${var.project_name}-event-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "EventId"
  attribute {
    name = "EventId"
    type = "S"
  }
  ttl {
    attribute_name = "ExpiresAt"
    enabled        = true
  }
}

resource "aws_cloudwatch_metric_alarm" "instance_status" {
  alarm_name          = "${var.project_name}-instance-status"
  alarm_description   = "EC2 instance status checks failing (not system status checks)"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_Instance"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "missing"
  dimensions = {
    InstanceId = var.monitored_instance_id
  }
}

resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-remediator"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = "ec2:DescribeInstances"
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = "ec2:RebootInstances"
        Resource = local.instance_arn
      },
      {
        Effect = "Allow"
        Action = "sns:Publish"
        Resource = aws_sns_topic.alerts.arn
      },
      {
        Effect = "Allow"
        Action = "dynamodb:PutItem"
        Resource = aws_dynamodb_table.events.arn
      }
    ]
  })
}

resource "aws_lambda_function" "remediator" {
  function_name    = "${var.project_name}-remediator"
  role             = aws_iam_role.lambda.arn
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  runtime          = "python3.12"
  handler          = "remediate.lambda_handler"
  timeout          = 20
  memory_size      = 128
  environment {
    variables = {
      TARGET_INSTANCE_ID = var.monitored_instance_id
      ALARM_NAME         = aws_cloudwatch_metric_alarm.instance_status.alarm_name
      ALARM_ARN          = aws_cloudwatch_metric_alarm.instance_status.arn
      SNS_TOPIC_ARN      = aws_sns_topic.alerts.arn
      DDB_TABLE_NAME     = aws_dynamodb_table.events.name
      REBOOT_ENABLED     = tostring(var.enable_reboot)
    }
  }
  depends_on = [aws_iam_role_policy.lambda]
}

resource "aws_cloudwatch_event_rule" "alarm" {
  name = "${var.project_name}-alarm-transition"
  description = "Trigger on one alarm moving to ALARM state"
  event_pattern = jsonencode({
    source = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    resources = [aws_cloudwatch_metric_alarm.instance_status.arn]
    detail = {
      alarmName = [aws_cloudwatch_metric_alarm.instance_status.alarm_name]
      state = { value = ["ALARM"] }
    }
  })
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.alarm.name
  target_id = "RemediationLambda"
  arn       = aws_lambda_function.remediator.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.remediator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.alarm.arn
}
