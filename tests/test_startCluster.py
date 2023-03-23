import json

import boto3
import pytest
from moto import mock_ecs, mock_sqs, mock_s3, mock_ec2

import run
import config
from tests.conftest import MONITOR_FILE


# startCluster will:
#   send a spot fleet request to moto-mocked-aws
#   create a APP_NAMESpotFleetRequestId.json file
#   once spot fleet request is ready (instantly), creat log groups for your log streams to go in
#   DS will ask aws moto-mocked-aws to place Docker containers onto the spot fleet instances
#   job will begin instantly

class TestGenerateECSConfig:
    @mock_ecs
    @mock_sqs
    def test_generate_ecs_config(self, s3, run_submitJob, tmp_path):
        if (config.AWS_REGION == "us-east-1"):
            # 'us-east-1' is the default region for S3 buckets
            # and is not a vallid arg for "LocationConstraint"
            s3.create_bucket(Bucket=config.AWS_BUCKET)
        else:
            s3.create_bucket(Bucket=config.AWS_BUCKET, CreateBucketConfiguration={"LocationConstraint": config.AWS_REGION})

        run_submitJob()

        res_endpoint = run.generateECSconfig(config.ECS_CLUSTER, config.APP_NAME, config.AWS_BUCKET, s3)

        expected_key = f"ecsconfigs/{config.APP_NAME}_ecs.config"
        expected_file_path = tmp_path / "configtemp.config"
        expected_file_endpoint = f"s3://{config.AWS_BUCKET}/{expected_key}"

        assert res_endpoint == expected_file_endpoint

        # create the file object to write to
        expected_file_path.touch()

        with expected_file_path.open('wb') as f:
            s3.download_fileobj(config.AWS_BUCKET, expected_key, f)
        
        res_file = expected_file_path.read_text()

        assert res_file == f"ECS_CLUSTER={config.ECS_CLUSTER}\nECS_AVAILABLE_LOGGING_DRIVERS=[\"json-file\",\"awslogs\"]"


class EarlyTermination(Exception):
    ...

def hijack_client(real_client, service_name):
    """
    Patches boto3.client so that an invocation of a service
    (eg 'ec2' or 'logs') will raise an EarlyTermination exception, allowing
    inspection and testing of the stack frame up until that point.
    """
    def f(*args, **kwargs):
        if (args[0] == service_name):
            raise EarlyTermination("early termination")
        
        return real_client(*args, **kwargs)
    
    return f

class TestSpotFleetConfig:

    @mock_ecs
    @mock_sqs
    @mock_s3
    def test_spot_fleet_config(self, run_startCluster, monkeypatch):
        monkeypatch.setattr(boto3, "client", hijack_client(boto3.client, 'ec2'))
        with pytest.raises(EarlyTermination) as e_info:
            run_startCluster()

        spot_fleet_config_res = None
        for tb in e_info.traceback:
            if (tb.name == "startCluster"):
                spot_fleet_config_res = tb.frame.f_locals["spotfleetConfig"]
        
        assert spot_fleet_config_res is not None

        # For config file requirements, see:
        # https://distributedscience.github.io/Distributed-Something/step_3_start_cluster.html#configuring-your-spot-fleet-request
        # For full config file specs, see:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/request_spot_fleet.html
        
        assert "IamFleetRole" in spot_fleet_config_res
        assert spot_fleet_config_res["IamFleetRole"].startswith("arn:aws:iam::")

        assert "ValidFrom" in spot_fleet_config_res
        assert "ValidUntil" in spot_fleet_config_res
        assert "TargetCapacity" in spot_fleet_config_res
        assert spot_fleet_config_res["TargetCapacity"] == config.CLUSTER_MACHINES
        assert "SpotPrice" in spot_fleet_config_res
        assert float(spot_fleet_config_res["SpotPrice"]) == pytest.approx(config.MACHINE_PRICE, rel=1e-2)

        launch_specs = spot_fleet_config_res["LaunchSpecifications"]
        for i in range(len(launch_specs)):
            assert "IamInstanceProfile" in launch_specs[i]
            assert "Arn" in launch_specs[i]["IamInstanceProfile"]
            assert launch_specs[i]["IamInstanceProfile"]["Arn"].startswith("arn:aws:iam::")

            assert "KeyName" in launch_specs[i]
            assert launch_specs[i]["KeyName"] == config.SSH_KEY_NAME[:-4]

            assert "ImageId" in launch_specs[i]
            assert launch_specs[i]["ImageId"].startswith("ami-")

            assert "NetworkInterfaces" in launch_specs[i]
            net_intfcs = launch_specs[i]["NetworkInterfaces"]
            for j in range(len(net_intfcs)):
                assert "SubnetId" in net_intfcs[j]
                assert net_intfcs[j]["SubnetId"].startswith("subnet-")

                assert "Groups" in net_intfcs[j]
                grps = net_intfcs[j]["Groups"]
                for k in range(len(grps)):
                    assert grps[k].startswith("sg-")

            assert "BlockDeviceMappings" in launch_specs[i]
            bdms = launch_specs[i]["BlockDeviceMappings"]
            
            assert "Ebs" in bdms[0]
            assert "SnapshotId" in bdms[0]["Ebs"]
            assert bdms[0]["Ebs"]["SnapshotId"].startswith("snap-")

            assert "Ebs" in bdms[1]
            assert "VolumeSize" in bdms[1]["Ebs"]
            assert bdms[1]["Ebs"]["VolumeSize"] == config.EBS_VOL_SIZE

            assert "InstanceType" in launch_specs[i]
            assert launch_specs[i]["InstanceType"] == config.MACHINE_TYPE[i]

            assert "UserData" in launch_specs[i]

    @mock_ecs
    @mock_sqs
    @mock_s3
    @mock_ec2
    def test_make_spot_fleet_request(self, run_startCluster, monkeypatch):
        monkeypatch.setattr(boto3, "client", hijack_client(boto3.client, 'logs'))
        with pytest.raises(EarlyTermination) as e_info:
            run_startCluster()

        request_info_res = None
        for tb in e_info.traceback:
            if (tb.name == "startCluster"):
                request_info_res = tb.frame.f_locals["requestInfo"]

        assert "SpotFleetRequestId" in request_info_res
        assert request_info_res["ResponseMetadata"]["HTTPStatusCode"] == 200

        ec2 = boto3.client("ec2")
        spot_fleet_request = ec2.describe_spot_fleet_requests(
            MaxResults=1,
            SpotFleetRequestIds=[request_info_res["SpotFleetRequestId"]]
        )

        assert len(spot_fleet_request["SpotFleetRequestConfigs"]) == 1


class TestCreateMonitor:
    @mock_ecs
    @mock_sqs
    @mock_s3
    @mock_ec2
    @pytest.mark.skip(reason="not implemented yet")
    def test_create_monitor(self, run_startCluster, monkeypatch):
        monkeypatch.setattr(boto3, "client", hijack_client(boto3.client, 'logs'))
        with pytest.raises(EarlyTermination) as e_info:
            run_startCluster()

        request_info_res = None
        for tb in e_info.traceback:
            if (tb.name == "startCluster"):
                request_info_res = tb.frame.f_locals["requestInfo"]

        assert MONITOR_FILE.exists()

        monitor_file_res = json.loads(MONITOR_FILE.read_text())
        
        print('.')


class TestStartCluster:
    @mock_ecs
    @mock_sqs
    @mock_s3
    @mock_ec2
    @pytest.mark.skip(reason="not implemented yet")
    def test_start_cluster(self, run_startCluster):
        run_startCluster()
