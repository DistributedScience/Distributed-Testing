import pytest
import os, sys
import boto3

from moto import mock_sqs, mock_ecs

from config import AWS_REGION


# WARNING: Do not import a module here or in any of the tests
# which instantiates a boto3 client or resource
# outside of a class/function
# see: https://docs.getmoto.org/en/latest/docs/getting_started.html#how-do-i-avoid-tests-from-mutating-my-real-infrastructure


current = os.path.dirname(os.path.realpath(__file__))
parent_directory = os.path.dirname(current)
sys.path.append(parent_directory)

@pytest.fixture(scope="function")
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = AWS_REGION

@pytest.fixture(scope="function")
def sqs(aws_credentials):
    with mock_sqs():
        yield boto3.client("sqs", region_name=os.environ["AWS_DEFAULT_REGION"])

@pytest.fixture(scope="function")
def ecs(aws_credentials):
    with mock_ecs():
        yield boto3.client("ecs", os.environ["AWS_DEFAULT_REGION"])
