"""Scoped CloudWatch alarm handler for one EC2 instance.

Reboot requires BOTH explicit Terraform opt-in and a tag on the instance.
All events generate structured log output; eligible alarms publish to SNS.
"""

import json
import os
import time


def process_event(event, *, ec2, sns, ddb, config):
    detail = event.get("detail", {})
    if (
        event.get("source") != "aws.cloudwatch"
        or event.get("detail-type") != "CloudWatch Alarm State Change"
        or detail.get("alarmName") != config["ALARM_NAME"]
        or detail.get("state", {}).get("value") != "ALARM"
        or config["ALARM_ARN"] not in event.get("resources", [])
    ):
        return {"result": "ignored", "reason": "unrelated-event"}

    event_id = event.get("id")
    if not event_id:
        return {"result": "ignored", "reason": "missing-event-id"}

    target = config["TARGET_INSTANCE_ID"]
    try:
        response = ec2.describe_instances(InstanceIds=[target])
        instance = response["Reservations"][0]["Instances"][0]
    except (KeyError, IndexError):
        return {"result": "ignored", "reason": "instance-not-found"}

    if instance.get("InstanceId") != target:
        return {"result": "ignored", "reason": "target-mismatch"}

    tags = {item["Key"]: item["Value"] for item in instance.get("Tags", [])}
    running = instance.get("State", {}).get("Name") == "running"
    opted_in = str(config["REBOOT_ENABLED"]).lower() == "true"
    allowed_tag = tags.get("PortfolioRemediation") == "allow"

    # Conditional write deduplicates EventBridge re-deliveries by event ID.
    try:
        ddb.put_item(
            TableName=config["DDB_TABLE_NAME"],
            Item={
                "EventId": {"S": event_id},
                "ExpiresAt": {"N": str(int(time.time()) + 3600)},
            },
            ConditionExpression="attribute_not_exists(EventId)",
        )
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return {"result": "ignored", "reason": "duplicate"}
        raise

    do_reboot = running and opted_in and allowed_tag
    message = {
        "alarm": config["ALARM_NAME"],
        "instance": target,
        "decision": "reboot" if do_reboot else "notify-only",
        "tag_authorized": allowed_tag,
        "instance_running": running,
    }

    if do_reboot:
        ec2.reboot_instances(InstanceIds=[target])

    sns.publish(
        TopicArn=config["SNS_TOPIC_ARN"],
        Subject="AWS cloud alert: " + ("reboot initiated" if do_reboot else "attention required"),
        Message=json.dumps(message),
    )
    print(json.dumps(message))
    return {"result": "reboot-requested" if do_reboot else "notified"}


def lambda_handler(event, _context):
    import boto3  # AWS Lambda Python runtime includes boto3.

    config = {key: os.environ[key] for key in (
        "TARGET_INSTANCE_ID", "ALARM_NAME", "ALARM_ARN", "SNS_TOPIC_ARN",
        "DDB_TABLE_NAME", "REBOOT_ENABLED"
    )}
    return process_event(
        event,
        ec2=boto3.client("ec2"),
        sns=boto3.client("sns"),
        ddb=boto3.client("dynamodb"),
        config=config,
    )
