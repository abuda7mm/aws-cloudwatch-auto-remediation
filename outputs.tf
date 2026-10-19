output "alarm_name" { value = aws_cloudwatch_metric_alarm.instance_status.alarm_name }
output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }
output "remediation_lambda_name" { value = aws_lambda_function.remediator.function_name }
