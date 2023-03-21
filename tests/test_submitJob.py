from moto import mock_sqs, mock_ecs

import run
import config


class TestJobQueue:
    @mock_sqs
    @mock_ecs
    def test_create_job_queue_instance(self, aws_config):
        run.setup()

        job_queue = run.JobQueue()

        expected_url = f"https://sqs.{config.AWS_REGION}.amazonaws.com/123456789012/{config.SQS_QUEUE_NAME}"

        assert job_queue is not None
        assert job_queue.queue.url == expected_url