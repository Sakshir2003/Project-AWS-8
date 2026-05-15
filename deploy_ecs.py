import boto3
import subprocess
import json
import base64
import time
import random
import string
import os

def generate_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))

def run_command(cmd):
    print(f"[CMD] {cmd}")
    # Using shell=True for powershell compatibility
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Command failed: {result.stderr}")
        raise Exception(f"Command failed: {cmd}")
    print(result.stdout)

def deploy_ecs():
    ecr = boto3.client('ecr', region_name='ap-south-1')
    ecs = boto3.client('ecs', region_name='ap-south-1')
    ec2 = boto3.client('ec2', region_name='ap-south-1')
    iam = boto3.client('iam')
    logs = boto3.client('logs', region_name='ap-south-1')
    
    uid = generate_id()
    repo_name = f"flask-app-repo-{uid}"
    cluster_name = f"FlaskCluster-{uid}"
    task_family = f"flask-task-{uid}"
    service_name = f"flask-service-{uid}"
    sg_name = f"ecs-flask-sg-{uid}"
    role_name = f"ecsTaskExecutionRole-{uid}"

    print("Starting Containerized Flask App Deployment...")

    # 1. Create ECR Repository
    print(f"[INFO] Creating Amazon ECR Repository: {repo_name}...")
    response = ecr.create_repository(repositoryName=repo_name)
    repository_uri = response['repository']['repositoryUri']
    registry_id = response['repository']['registryId']
    print(f"[OK] Repository created: {repository_uri}")

    # 2. Docker Login, Build, and Push
    print("[INFO] Authenticating Docker with ECR...")
    auth_token = ecr.get_authorization_token(registryIds=[registry_id])
    token = auth_token['authorizationData'][0]['authorizationToken']
    password = base64.b64decode(token).decode('utf-8').split(':')[1]
    endpoint = auth_token['authorizationData'][0]['proxyEndpoint']
    
    # Strip https:// for docker login command
    login_url = endpoint.replace('https://', '')
    
    run_command(f"docker login -u AWS -p {password} {login_url}")
    
    print("[INFO] Building Docker image...")
    run_command("docker build -t flask-app .")
    
    print("[INFO] Tagging and Pushing Docker image to ECR...")
    run_command(f"docker tag flask-app:latest {repository_uri}:latest")
    run_command(f"docker push {repository_uri}:latest")
    print("[OK] Docker image successfully pushed to ECR!")

    # 3. Create Execution Role for ECS
    print("[INFO] Setting up IAM Execution Role for ECS Tasks...")
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}]
    }
    try:
        iam.create_role(RoleName=role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
        iam.attach_role_policy(RoleName=role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy")
        print(f"[OK] IAM Role '{role_name}' created.")
        time.sleep(10) # Wait for IAM propagation
    except Exception as e:
        print(f"[INFO] IAM Role creation skipped (might already exist): {e}")
    
    role_info = iam.get_role(RoleName=role_name)
    execution_role_arn = role_info['Role']['Arn']

    # 3.5 Create CloudWatch Log Group
    log_group_name = f'/ecs/{task_family}'
    print(f"[INFO] Creating CloudWatch Log Group '{log_group_name}'...")
    logs.create_log_group(logGroupName=log_group_name)
    print("[OK] Log Group created.")

    # 4. Create ECS Cluster
    print(f"[INFO] Creating Amazon ECS Cluster '{cluster_name}'...")
    ecs.create_cluster(clusterName=cluster_name)
    print("[OK] Cluster created.")

    # 5. Register Task Definition (Fargate)
    print("[INFO] Registering Fargate Task Definition...")
    task_definition = ecs.register_task_definition(
        family=task_family,
        networkMode='awsvpc',
        requiresCompatibilities=['FARGATE'],
        cpu='256',
        memory='512',
        executionRoleArn=execution_role_arn,
        containerDefinitions=[
            {
                'name': 'flask-container',
                'image': f"{repository_uri}:latest",
                'essential': True,
                'portMappings': [{'containerPort': 5000, 'protocol': 'tcp'}],
                'logConfiguration': {
                    'logDriver': 'awslogs',
                    'options': {
                        'awslogs-group': f'/ecs/{task_family}',
                        'awslogs-region': 'ap-south-1',
                        'awslogs-stream-prefix': 'ecs'
                    }
                }
            }
        ]
    )
    task_def_arn = task_definition['taskDefinition']['taskDefinitionArn']
    print("[OK] Task Definition registered.")

    # 6. Security Group for Fargate Tasks
    vpcs = ec2.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
    vpc_id = vpcs['Vpcs'][0]['VpcId']
    
    sg = ec2.create_security_group(GroupName=sg_name, Description='Allow Port 5000 for Flask container', VpcId=vpc_id)
    sg_id = sg['GroupId']
    ec2.authorize_security_group_ingress(GroupId=sg_id, IpPermissions=[{'IpProtocol': 'tcp', 'FromPort': 5000, 'ToPort': 5000, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}])
    
    subnets = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
    subnet_ids = [s['SubnetId'] for s in subnets['Subnets']][:2]

    # 7. Create Service Linked Role (Required for new AWS accounts)
    try:
        iam.create_service_linked_role(AWSServiceName='ecs.amazonaws.com')
        print("[INFO] Created ECS Service-Linked Role.")
        time.sleep(5)
    except Exception:
        pass # Already exists

    # 8. Create ECS Service
    print(f"[INFO] Creating ECS Fargate Service '{service_name}'...")
    for attempt in range(12):
        try:
            ecs.create_service(
                cluster=cluster_name,
                serviceName=service_name,
                taskDefinition=task_def_arn,
                launchType='FARGATE',
                desiredCount=1,
                networkConfiguration={
                    'awsvpcConfiguration': {
                        'subnets': subnet_ids,
                        'securityGroups': [sg_id],
                        'assignPublicIp': 'ENABLED'
                    }
                }
            )
            print("[OK] ECS Service created. AWS is spinning up your container!")
            break
        except Exception as e:
            if 'Unable to assume the service linked role' in str(e) or 'does not exist' in str(e):
                print(f"[RETRY] ECS Service Role propagating. Retrying in 10s... (Attempt {attempt+1}/12)")
                time.sleep(10)
            else:
                raise e
    else:
        print("Error: Could not create ECS Service due to IAM propagation timeout.")
        return

    # 9. Fetch the Public IP gracefully
    print("[INFO] Waiting for Fargate Task to be RUNNING so we can fetch its Public IP (takes ~1-2 mins)...")
    time.sleep(10)
    
    tasks = ecs.list_tasks(cluster=cluster_name, serviceName=service_name)
    while not tasks.get('taskArns'):
        time.sleep(5)
        tasks = ecs.list_tasks(cluster=cluster_name, serviceName=service_name)
        
    task_arn = tasks['taskArns'][0]
    
    waiter = ecs.get_waiter('tasks_running')
    waiter.wait(cluster=cluster_name, tasks=[task_arn])
    
    task_desc = ecs.describe_tasks(cluster=cluster_name, tasks=[task_arn])
    attachments = task_desc['tasks'][0]['attachments'][0]['details']
    eni_id = next(item['value'] for item in attachments if item['name'] == 'networkInterfaceId')
    
    eni_info = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    public_ip = eni_info['NetworkInterfaces'][0]['Association']['PublicIp']

    print("\n============================================================")
    print("Deployment Triggered Successfully!")
    print(f"Docker Image pushed to: {repository_uri}")
    print(f"ECS Cluster: {cluster_name}")
    print(f"Fargate Task: RUNNING")
    print(f"\nAccess your Containerized Flask App here: http://{public_ip}:5000")
    print("============================================================")

if __name__ == "__main__":
    deploy_ecs()
