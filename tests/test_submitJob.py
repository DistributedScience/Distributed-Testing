import sys
import json

import boto3
from moto import mock_sqs, mock_ecs

import run
import config
from tests.conftest import JOB_FILE


class TestJobQueue:
    @mock_sqs
    @mock_ecs
    def test_create_job_queue_instance(self, aws_config):
        run.setup()

        job_queue = run.JobQueue()

        expected_url = f"https://sqs.{config.AWS_REGION}.amazonaws.com/123456789012/{config.SQS_QUEUE_NAME}"

        assert job_queue is not None
        assert job_queue.queue.url == expected_url


class TestJobFile:
    def test_job_file(self):
        assert JOB_FILE.exists()


class TestSubmitJob:
    @mock_ecs
    @mock_sqs
    def test_submit_job(self, aws_config, monkeypatch):
        run.setup()

        monkeypatch.setattr(sys, "argv", ["run.py", "submitJob", str(JOB_FILE)])

        run.submitJob()

        sqs = boto3.resource('sqs')
        queue = sqs.get_queue_by_name(QueueName=config.SQS_QUEUE_NAME)
        job_info = json.loads(JOB_FILE.read_text())
        templateMessage = {
            eachkey:job_info[eachkey] for eachkey in job_info.keys() if eachkey != "groups" and "_comment" not in eachkey
        }

        expected_messages = []
        for batch in job_info["groups"]:
            msg = templateMessage.copy()
            msg["group"] = batch
            expected_messages.append(msg)

        assert queue.attributes['ApproximateNumberOfMessages'] == str(len(expected_messages))
        
        for _ in range(len(expected_messages)):
            received_msg = queue.receive_messages(MaxNumberOfMessages=1)
            assert len(received_msg) == 1
            received_msg = json.loads(received_msg[0].body)
            assert received_msg in expected_messages
        
        # should have no more messages
        final_received_msg = queue.receive_messages(MaxNumberOfMessages=1)
        assert len(final_received_msg) == 0
