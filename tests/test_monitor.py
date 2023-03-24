import json

import boto3
from pytest import fixture
from moto import mock_ecs, mock_sqs, mock_s3, mock_ec2, mock_logs, mock_cloudwatch

import run
import config
from tests.conftest import MONITOR_FILE



class TestMonitor:
    @mock_ecs
    @mock_sqs
    @mock_s3
    @mock_ec2
    @mock_logs
    @mock_cloudwatch
    def test_monitor(self, monitor):
        monitor()

        print('.')