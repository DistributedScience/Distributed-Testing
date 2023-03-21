import json
from textwrap import dedent

import pytest
from moto import mock_sqs, mock_ecs

import config
import run
from tests.conftest import FAKE_AWS_ACCESS_KEY_ID, FAKE_AWS_SECRET_ACCESS_KEY


@pytest.fixture(scope="module")
def no_wait():
    run.WAIT_TIME = 0


class TestGetQueueURL:
    queue_name = "test_queue"

    def test_get_nonexistent_queue_url(self, sqs):
        url = run.get_queue_url(sqs, self.queue_name)
        assert url is None

    def test_get_existing_queue_url(self, sqs):
        sqs.create_queue(QueueName=self.queue_name)
        url = run.get_queue_url(sqs,self.queue_name)
        assert url is not None
        assert url == f"https://sqs.{config.AWS_REGION}.amazonaws.com/123456789012/{self.queue_name}"

class TestGetOrCreateQueue:
    def test_create_nonexistent_dead_queue(self, sqs, no_wait):
        run.get_or_create_queue(sqs)
        res = sqs.list_queues()

        res_urls = sorted(res['QueueUrls'])

        expected_urls = sorted([
            f"https://sqs.{config.AWS_REGION}.amazonaws.com/123456789012/{config.SQS_DEAD_LETTER_QUEUE}",
            f"https://sqs.{config.AWS_REGION}.amazonaws.com/123456789012/{config.SQS_QUEUE_NAME}"
        ])

        assert res_urls == expected_urls

        dead_url = run.get_queue_url(sqs, config.SQS_DEAD_LETTER_QUEUE)
        dead_queue_arn = sqs.get_queue_attributes(
            QueueUrl=dead_url, AttributeNames=["All"]
        )

        queue_url = run.get_queue_url(sqs, config.SQS_QUEUE_NAME)
        queue_arn = sqs.get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=["All"]
        )

        assert "QueueArn" in dead_queue_arn["Attributes"]
        assert "RedrivePolicy" in queue_arn["Attributes"]

        redrive_policy = json.loads(queue_arn["Attributes"]["RedrivePolicy"])
        redrive_policy_arn = redrive_policy["deadLetterTargetArn"]

        assert redrive_policy_arn == dead_queue_arn["Attributes"]["QueueArn"]


    def test_create_existing_dead_queue(self, sqs, no_wait):
        sqs.create_queue(QueueName=config.SQS_DEAD_LETTER_QUEUE)
        run.get_or_create_queue(sqs)
        res = sqs.list_queues()

        res_urls = sorted(res['QueueUrls'])

        expected_urls = sorted([
            f"https://sqs.{config.AWS_REGION}.amazonaws.com/123456789012/{config.SQS_DEAD_LETTER_QUEUE}",
            f"https://sqs.{config.AWS_REGION}.amazonaws.com/123456789012/{config.SQS_QUEUE_NAME}"
        ])

        assert res_urls == expected_urls

    def test_create_existing_queue(self, sqs, no_wait):
        sqs.create_queue(QueueName=config.SQS_QUEUE_NAME)
        run.get_or_create_queue(sqs)
        res = sqs.list_queues()

        res_urls = sorted(res['QueueUrls'])

        expected_urls = sorted([
            f"https://sqs.{config.AWS_REGION}.amazonaws.com/123456789012/{config.SQS_DEAD_LETTER_QUEUE}",
            f"https://sqs.{config.AWS_REGION}.amazonaws.com/123456789012/{config.SQS_QUEUE_NAME}"
        ])

        assert res_urls == expected_urls

class TestGetOrCreateCluster:
    def test_create_nonexistent_cluster(self, ecs, no_wait):
        run.get_or_create_cluster(ecs)
        res = ecs.list_clusters()
        assert res["clusterArns"] == [f"arn:aws:ecs:{config.AWS_REGION}:123456789012:cluster/{config.ECS_CLUSTER}"]

    def test_create_existing_cluster(self, ecs, no_wait):
        ecs.create_cluster(clusterName=config.ECS_CLUSTER)
        run.get_or_create_cluster(ecs)
        res = ecs.list_clusters()
        assert res["clusterArns"] == [f"arn:aws:ecs:{config.AWS_REGION}:123456789012:cluster/{config.ECS_CLUSTER}"]

class TestGenerateTaskDefinition:
    def test_generate_task_definition(self, aws_config, sqs, ecs, no_wait):
        run.get_or_create_queue(sqs)
        run.get_or_create_cluster(ecs)
        task_definition, taskRoleArn = run.generate_task_definition(config.AWS_PROFILE)

        assert taskRoleArn == False

        task_def_env = task_definition["containerDefinitions"][0]["environment"]
        
        aws_access_key_id_res = list(filter(
            lambda x: x["name"] == "AWS_ACCESS_KEY_ID",
            task_def_env
        ))

        aws_secret_access_key_res = list(filter(
            lambda x: x["name"] == "AWS_SECRET_ACCESS_KEY", task_def_env
        ))

        queue_name_res = list(filter(
            lambda x: x["name"] == "SQS_QUEUE_URL",
            task_def_env
        ))

        assert len(aws_access_key_id_res) == 1
        assert len(aws_secret_access_key_res) == 1
        assert len(queue_name_res) == 1

        assert aws_access_key_id_res[0]["value"] == FAKE_AWS_ACCESS_KEY_ID
        assert aws_secret_access_key_res[0]["value"] == FAKE_AWS_SECRET_ACCESS_KEY
        assert queue_name_res[0]["value"] == run.get_queue_url(sqs, config.SQS_QUEUE_NAME)

    @pytest.mark.skip("Not yet implemented")
    def test_generate_task_definition_role_arn(self, aws_config, sqs, ecs, no_wait):
        # TODO: add role_arn option
        aws_config['aws_config_file'].write_text(dedent(
            f"""
            [default]
            aws_access_key_id = testing
            aws_secret_access_key = testing
            """
        ))

        run.get_or_create_queue(sqs)
        run.get_or_create_cluster(ecs)
        task_definition, taskRoleArn = run.generate_task_definition(config.AWS_PROFILE)

        assert taskRoleArn == True

class TestUpdateECSTaskDefinition:
    ecs_task_name = config.APP_NAME + 'Task'

    @pytest.mark.skip(reason="Not yet ready - needs to change aws credentials parsing")
    @mock_sqs
    def test_update_ecs_task_definition(self, ecs, no_wait):
        run.update_ecs_task_definition(ecs, self.ecs_task_name, config.AWS_PROFILE)
        res = ecs.list_task_definitions()
        assert res["taskDefinitionArns"] == [f"arn:aws:ecs:{config.AWS_REGION}:123456789012:task-definition/{config.ECS_TASK_DEFINITION}:1"]

class TestSetup:
    @mock_sqs
    @mock_ecs
    @pytest.mark.skip(reason="Not yet safe to run")
    def test_setup(self, aws_config, no_wait):
        run.setup()
        
