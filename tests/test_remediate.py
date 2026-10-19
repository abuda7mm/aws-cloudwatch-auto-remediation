import unittest
from lambda_code import process_event

CONFIG = {
    "ALARM_NAME": "demo-instance-status",
    "ALARM_ARN": "arn:aws:cloudwatch:eu-north-1:123456789012:alarm:demo-instance-status",
    "TARGET_INSTANCE_ID": "i-0123456789abcdef0",
    "SNS_TOPIC_ARN": "arn:aws:sns:eu-north-1:123456789012:demo",
    "DDB_TABLE_NAME": "events",
    "REBOOT_ENABLED": "false",
}
EVENT = {
    "id": "event-123", "source": "aws.cloudwatch",
    "detail-type": "CloudWatch Alarm State Change",
    "resources": [CONFIG["ALARM_ARN"]],
    "detail": {"alarmName": CONFIG["ALARM_NAME"], "state": {"value": "ALARM"}},
}

class FakeEC2:
    def __init__(self, allow=True):
        self.allow = allow
        self.reboots = []
    def describe_instances(self, InstanceIds):
        return {"Reservations": [{"Instances": [{
            "InstanceId": InstanceIds[0], "State": {"Name": "running"},
            "Tags": [{"Key": "PortfolioRemediation", "Value": "allow" if self.allow else "deny"}],
        }]}]}
    def reboot_instances(self, InstanceIds):
        self.reboots.append(InstanceIds[0])

class FakeSNS:
    def __init__(self): self.messages = []
    def publish(self, **kwargs): self.messages.append(kwargs)

class FakeDDB:
    def __init__(self): self.items = []
    def put_item(self, **kwargs): self.items.append(kwargs)

class HandlerTests(unittest.TestCase):
    def test_other_alarm_ignored(self):
        ec2, sns, ddb = FakeEC2(), FakeSNS(), FakeDDB()
        bad = dict(EVENT, resources=["something-else"])
        self.assertEqual(process_event(bad, ec2=ec2, sns=sns, ddb=ddb, config=CONFIG)["result"], "ignored")
        self.assertEqual(len(sns.messages), 0)

    def test_notify_only_by_default(self):
        ec2, sns, ddb = FakeEC2(), FakeSNS(), FakeDDB()
        result = process_event(EVENT, ec2=ec2, sns=sns, ddb=ddb, config=CONFIG)
        self.assertEqual(result["result"], "notified")
        self.assertEqual(ec2.reboots, [])
        self.assertEqual(len(sns.messages), 1)
        self.assertEqual(len(ddb.items), 1)

    def test_reboot_with_two_approvals(self):
        ec2, sns, ddb = FakeEC2(), FakeSNS(), FakeDDB()
        config = dict(CONFIG, REBOOT_ENABLED="true")
        result = process_event(EVENT, ec2=ec2, sns=sns, ddb=ddb, config=config)
        self.assertEqual(result["result"], "reboot-requested")
        self.assertEqual(ec2.reboots, [CONFIG["TARGET_INSTANCE_ID"]])

    def test_no_reboot_without_instance_tag(self):
        ec2, sns, ddb = FakeEC2(allow=False), FakeSNS(), FakeDDB()
        config = dict(CONFIG, REBOOT_ENABLED="true")
        result = process_event(EVENT, ec2=ec2, sns=sns, ddb=ddb, config=config)
        self.assertEqual(result["result"], "notified")
        self.assertEqual(ec2.reboots, [])

if __name__ == "__main__":
    unittest.main()
