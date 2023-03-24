import os, sys
from textwrap import dedent
from pathlib import Path

import pytest
import boto3
from moto import mock_sqs, mock_ecs, mock_s3, mock_ec2

import run
from config import AWS_REGION, AWS_PROFILE, AWS_BUCKET, APP_NAME


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

JOB_FILE = Path(__file__).parent.parent / "files/exampleJob.json"
FLEET_FILE = Path(__file__).parent.parent / "files/exampleFleet_us-east-1.json"
# does not exist unless startCluster has been run
MONITOR_FILE = Path(__file__).parent.parent / f"files/{APP_NAME}SpotFleetRequestId.json"


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
        yield boto3.client("sqs", region_name=AWS_REGION)


@pytest.fixture(scope="function")
def ecs():
    with mock_ecs():
        yield boto3.client("ecs", region_name=AWS_REGION)


@pytest.fixture(scope="function")
def s3():
    with mock_s3():
        yield boto3.client("s3", region_name=AWS_REGION)

@pytest.fixture(scope="function")
def ec2():
    with mock_ec2():
        yield boto3.client("ec2", region_name=AWS_REGION)


@pytest.fixture(scope="function")
def protect_monitor_file():
    # read in the current contents, if any
    curr = None
    if MONITOR_FILE.exists():
        curr = MONITOR_FILE.read_text()

    # do something that may or may not write to the file
    yield MONITOR_FILE
    
    # clean up by putting the original contents back, if any
    if curr:
        MONITOR_FILE.write_text(curr)
    # or delete the file if it didn't exist before
    else:
        MONITOR_FILE.unlink()


# Below functions are fixtures that run steps 1 - 4
#
# The reason they return callbacks, instead of calling the run.x() functions
# directly is because the moto mock decorators must be applied to the test
# before running run.x().
#
# We can't decorate the fixtures themselves with moto mock decorators 
# because while the run.x() functions within the fixtures would be mocked,
# the runx.x() functions within the tests using the fixtures would NOT be.
# Therefor we return a non-mocked callback, the tests are decorated with
# mocks, and then the tests invoke the callback returned by the fixture.


# mock sqs and ecs before running cb
@pytest.fixture(scope="function")
def run_setup(aws_config):
    def f():
        run.setup()

    return f


# mock sqs and ecs before running cb
@pytest.fixture(scope="function")
def run_submitJob(run_setup, monkeypatch):
    def f():
        # don't put this outside of the callback, else it may be overwritten
        monkeypatch.setattr(sys, "argv", ["run.py", "submitJob", str(JOB_FILE)])

        run_setup()
        run.submitJob()

    return f


# mock sqs, ecs, s3, ec2 and logs before running cb
@pytest.fixture(scope="function")
def run_startCluster(run_submitJob, monkeypatch, protect_monitor_file):
    def f():
        s3 = boto3.client('s3')

        if (AWS_REGION == "us-east-1"):
            # 'us-east-1' is the default region for S3 buckets
            # and is not a vallid arg for "LocationConstraint"
            s3.create_bucket(Bucket=AWS_BUCKET)
        else:
            s3.create_bucket(Bucket=AWS_BUCKET, CreateBucketConfiguration={"LocationConstraint": AWS_REGION})

        run_submitJob()
        
        # don't put this outside of the callback, else it may be overwritten
        monkeypatch.setattr(sys, "argv", ["run.py", "startCluster", str(FLEET_FILE)])
        
        run.startCluster()

    return f
