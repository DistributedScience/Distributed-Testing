import pytest

from moto import mock_sqs

from config import SQS_QUEUE_NAME

import json


@mock_sqs
def test_setup(aws_credentials):
    import run
    run.WAIT_TIME = 0
    run.setup()
