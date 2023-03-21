import os, sys
from textwrap import dedent

import pytest
import boto3
from moto import mock_sqs, mock_ecs

import run
from config import AWS_REGION, AWS_PROFILE


# WARNING: Do not import a module here or in any of the tests
# which instantiates a boto3 client or resource
# outside of a class/function
# see: https://docs.getmoto.org/en/latest/docs/getting_started.html#how-do-i-avoid-tests-from-mutating-my-real-infrastructure


current = os.path.dirname(os.path.realpath(__file__))
parent_directory = os.path.dirname(current)
sys.path.append(parent_directory)

# moto overrides this with 'foobar_key'
FAKE_AWS_ACCESS_KEY_ID = 'testing'
# FAKE_AWS_ACCESS_KEY_ID = 'DSVXIXRSGIYFOFBIDXS'
# moto overrides this with 'foobar_secret'
FAKE_AWS_SECRET_ACCESS_KEY = 'testing'
# FAKE_AWS_SECRET_ACCESS_KEY = '5ZnXLgC!Ta61t6k9LlVP(mgIRHr#xlQyr&Ltfiox'

FAKE_AWS_SECURITY_TOKEN = 'testing'
FAKE_AWS_SESSION_TOKEN = 'testing'


@pytest.fixture(autouse=True, scope="session")
def no_wait():
    run.WAIT_TIME = 0
    run.MONITOR_TIME = 0


@pytest.fixture(autouse=True, scope="session")
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    # moto overrides these two; put here "just in case"
    # to override moto's override, order fixtures such that
    # these two occur strictly after moto does its stuff
    os.environ["AWS_ACCESS_KEY_ID"] = FAKE_AWS_ACCESS_KEY_ID
    os.environ["AWS_SECRET_ACCESS_KEY"] = FAKE_AWS_SECRET_ACCESS_KEY

    os.environ["AWS_SECURITY_TOKEN"] = FAKE_AWS_SECURITY_TOKEN
    os.environ["AWS_SESSION_TOKEN"] = FAKE_AWS_SESSION_TOKEN

    os.environ["AWS_DEFAULT_REGION"] = AWS_REGION


@pytest.fixture(scope="function")
def aws_config(monkeypatch, tmp_path):
    """
    Mocked AWS Config for moto.

    Monkeypatches os.environ to create a fake
    ~/.aws/config file
    """
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    aws_config_file = aws_dir / "config"
    aws_creds_file = aws_dir / "credentials"
    
    aws_config_file.write_text(dedent(
        f"""
        [{AWS_PROFILE}]
        aws_access_key_id = {FAKE_AWS_ACCESS_KEY_ID}
        aws_secret_access_key = {FAKE_AWS_SECRET_ACCESS_KEY}
        """
    ))
    aws_creds_file.write_text(dedent(
        f"""
        [{AWS_PROFILE}]
        output = json
        region = us-east-1
        aws_access_key_id = {FAKE_AWS_ACCESS_KEY_ID}
        aws_secret_access_key = {FAKE_AWS_SECRET_ACCESS_KEY}
        """
    ))

    # monkeypatch os.environ to point to our fake files
    monkeypatch.setenv("HOME", str(tmp_path))

    # return in case we want to override config or credentials file contents
    return {"aws_dir": aws_dir, "aws_config_file": aws_config_file, "aws_creds_file": aws_creds_file}


@pytest.fixture(scope="function")
def sqs():
    with mock_sqs():
        yield boto3.client("sqs", region_name=os.environ["AWS_DEFAULT_REGION"])


@pytest.fixture(scope="function")
def ecs():
    with mock_ecs():
        yield boto3.client("ecs", os.environ["AWS_DEFAULT_REGION"])
