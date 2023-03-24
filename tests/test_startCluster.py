import json

import boto3
import pytest
from moto import mock_ecs, mock_sqs, mock_s3, mock_ec2, mock_logs

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

def hijack_client(real_client, service_name, service_fn=None, service_count=1, service_fn_count=1):
    """
    If service_fn is None,
    Patches boto3.client('<some_service>') so that an invocation of a service
    (eg 'ec2' or 'logs') will raise an EarlyTermination exception, allowing
    inspection and testing of the stack frame up until that point.

    If service_fn is not None,
    Patches boto3.client('<some_service>').<service_fn> so that an invocation
    of a service function (eg 'put_retention_policy') will raise an EarlyTermination
    exception, allowing inspection and testing of the stack frame up until that point.

    'service_count' represents the number of times the service can be called
    before the EarlyTermination exception is raised.
    
    `service_fn_count` represents the number of times the service function can be called
    before the EarlyTermination exception is raised.
    """
    if service_fn is None:
        real_client._called_n_times = service_count

    def f(*args, **kwargs):
        real_client_obj = real_client(*args, **kwargs)

        if service_fn is None and args[0] == service_name:
            real_client._called_n_times -= 1
            if real_client._called_n_times == 0:
                raise EarlyTermination("early termination")

        elif service_fn is not None and args[0] == service_name:
            real_client_obj._called_n_times = service_fn_count

            real_fn = getattr(real_client_obj, service_fn)

            def hijacked_fn(*args, **kwargs):
                res = real_fn(*args, **kwargs)
                real_client_obj._called_n_times -= 1
                if real_client_obj._called_n_times == 0:
                    raise EarlyTermination("early termination")
            
            setattr(real_client_obj, service_fn, hijacked_fn)

        return real_client_obj
    
    return f


class TestSpotFleetConfig:
    @mock_ecs
    @mock_sqs
    @mock_s3
    def test_spot_fleet_config(self, run_startCluster, monkeypatch):
        """
        startCluster Step 1: set up the configuration files
        """
        monkeypatch.setattr(boto3, "client", hijack_client(boto3.client, 'ec2'))
        with pytest.raises(EarlyTermination) as e_info:
            run_startCluster()

        spot_fleet_config_res = None
        for tb in e_info.traceback:
            if (tb.name == "startCluster"):
                spot_fleet_config_res = tb.locals["spotfleetConfig"]
        
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
        """
        startCluster Step 2: make the spot fleet request
        """
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
    def test_create_monitor(self, run_startCluster, monkeypatch):
        """
        startCluster Step 3: Make the monitor
        """
        monkeypatch.setattr(boto3, "client", hijack_client(boto3.client, 'logs'))
        with pytest.raises(EarlyTermination) as e_info:
            run_startCluster()

        request_info_res = None
        for tb in e_info.traceback:
            if (tb.name == "startCluster"):
                request_info_res = tb.locals["requestInfo"]

        assert MONITOR_FILE.exists()

        monitor_file_res = json.loads(MONITOR_FILE.read_text())
        
        assert monitor_file_res["MONITOR_FLEET_ID"] == request_info_res["SpotFleetRequestId"]
        assert monitor_file_res["MONITOR_APP_NAME"] == config.APP_NAME
        assert monitor_file_res["MONITOR_ECS_CLUSTER"] == config.ECS_CLUSTER
        assert monitor_file_res["MONITOR_QUEUE_NAME"] == config.SQS_QUEUE_NAME
        assert monitor_file_res["MONITOR_BUCKET_NAME"] == config.AWS_BUCKET
        assert monitor_file_res["MONITOR_LOG_GROUP_NAME"] == config.LOG_GROUP_NAME


class TestCreateLogGroup:
    @mock_ecs
    @mock_sqs
    @mock_s3
    @mock_ec2
    @mock_logs
    def test_create_log_group(self, run_startCluster, monkeypatch):
        """
        startCluster Step 4: Create the log group
        """
        monkeypatch.setattr(boto3, "client", hijack_client(
            boto3.client,
            'logs',
            service_fn='put_retention_policy',
            service_fn_count=2
        ))

        with pytest.raises(EarlyTermination) as e_info:
            run_startCluster()

        put_retention_policy_res = e_info.traceback[-1].locals["res"]

        assert put_retention_policy_res is not None
        assert put_retention_policy_res["ResponseMetadata"]["HTTPStatusCode"] == 200

        logs = boto3.client("logs")
        log_group_info_res = logs.describe_log_groups(logGroupNamePrefix=config.LOG_GROUP_NAME)

        assert "logGroups" in log_group_info_res
        log_groups = log_group_info_res["logGroups"]
        
        name_log_groups = list(filter(
            lambda lg: lg["logGroupName"] == config.LOG_GROUP_NAME, log_groups
        ))

        per_instance_log_groups = list(filter(
            lambda lg: lg["logGroupName"] == config.LOG_GROUP_NAME + "_perInstance", log_groups
        ))

        assert len(name_log_groups) == 1
        assert len(per_instance_log_groups) == 1

        assert name_log_groups[0]["arn"] == f"arn:aws:logs:{config.AWS_REGION}:123456789012:log-group:{config.LOG_GROUP_NAME}"
        assert per_instance_log_groups[0]["arn"] == f"arn:aws:logs:{config.AWS_REGION}:123456789012:log-group:{config.LOG_GROUP_NAME}_perInstance"


class TestUpdateService:
    @mock_ecs
    @mock_sqs
    @mock_s3
    @mock_ec2
    @mock_logs
    def test_update_service(self, run_startCluster, monkeypatch):
        """
        startCluster Step 5: update the ECS service to be ready
        to inject docker containers in EC2 instances
        """
        monkeypatch.setattr(boto3, "client", hijack_client(
            boto3.client,
            'ecs',
            service_fn='update_service',
        ))

        with pytest.raises(EarlyTermination) as e_info:
            run_startCluster()

        update_service_res = e_info.traceback[-1].locals["res"]

        assert update_service_res is not None
        assert update_service_res["ResponseMetadata"]["HTTPStatusCode"] == 200

        ecs = boto3.client("ecs")

        res_service = ecs.describe_services(cluster=config.ECS_CLUSTER, services=[f"{config.APP_NAME}Service"])

        assert len(res_service["services"]) >= 1

        res_service = res_service["services"][0]

        assert int(res_service["desiredCount"]) == config.CLUSTER_MACHINES * config.TASKS_PER_MACHINE


class TestMonitorInstanceCreation:
    @mock_ecs
    @mock_sqs
    @mock_s3
    @mock_ec2
    @mock_logs
    def test_monitor_instance_creation(self, run_startCluster, monkeypatch):
        """
        startCluster Step 6: Monitor the creation of the instances until all are present
        """
        monkeypatch.setattr(boto3, "client", hijack_client(
            boto3.client,
            'ec2',
            service_fn='describe_spot_fleet_instances',
        ))

        with pytest.raises(EarlyTermination) as e_info:
            run_startCluster()

        describe_spot_fleet_instances_res = e_info.traceback[-1].locals["res"]

        assert describe_spot_fleet_instances_res is not None
        assert describe_spot_fleet_instances_res["ResponseMetadata"]["HTTPStatusCode"] == 200
        assert len(describe_spot_fleet_instances_res["ActiveInstances"]) == config.CLUSTER_MACHINES


class TestStartCluster:
    @mock_ecs
    @mock_sqs
    @mock_s3
    @mock_logs
    def test_start_cluster(self, ec2, run_startCluster):
        run_startCluster()

        spot_fleet_request = ec2.describe_spot_fleet_requests()
        
        assert "ResponseMetadata" in spot_fleet_request
        assert spot_fleet_request["ResponseMetadata"]["HTTPStatusCode"] == 200
        assert "SpotFleetRequestConfigs" in spot_fleet_request
        assert len(spot_fleet_request["SpotFleetRequestConfigs"]) == 1

        spot_fleet_request_config = spot_fleet_request["SpotFleetRequestConfigs"][0]
        spot_fleet_request_id = spot_fleet_request_config["SpotFleetRequestId"]

        status = ec2.describe_spot_fleet_instances(SpotFleetRequestId=spot_fleet_request_id)

        assert "ResponseMetadata" in status
        assert status["ResponseMetadata"]["HTTPStatusCode"] == 200
        assert "ActiveInstances" in status
        assert len(status["ActiveInstances"]) == config.CLUSTER_MACHINES

        assert MONITOR_FILE.exists()
