# Project-AWS-8
# Containerized Flask Application

This project takes a standard Python Flask web application, containerizes it using Docker, and fully automates its deployment to AWS using Serverless Containers.

## Architecture Pipeline
1. **Docker Engine**: The script natively uses your local Docker installation to build a lightweight Linux container containing the Flask app.
2. **Amazon ECR (Elastic Container Registry)**: The script automatically logs into AWS via Docker and pushes the newly built container image securely to the cloud.
3. **Amazon ECS (Elastic Container Service)**: The script creates an ECS Cluster and a Task Definition pointing to the newly pushed container.
4. **AWS Fargate**: Instead of managing EC2 instances, this project uses Fargate. It tells AWS to simply run the container in a serverless capacity without provisioning any underlying servers manually. 

## How to Deploy
1. Ensure Docker Desktop is running on your machine.
2. Execute the python file:
```powershell
python deploy_ecs.py
```

The script will handle the image build, the cloud push, and the infrastructure setup. At the end, it will intelligently fetch the raw Public IP of the running Fargate task and provide you with the web URL!
