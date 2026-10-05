# Deployment guide

This is a manual reconstruction guide, not a one-command deployment. No resources were created during portfolio preparation. Running AWS deployment commands can incur charges.

## 1. Network/bootstrap template

`infra/network.yaml` creates a VPC, two public subnets, an internet gateway, routes, security groups and an EC2 Docker-build host.

Supply these CloudFormation parameters:

| Parameter | Value to provide |
| --- | --- |
| `AdminCidr` | Your trusted source IPv4 CIDR, ideally a single `/32` |
| `ImageId` | An Amazon Linux 2023 AMI available in your region |
| `KeyName` | An existing EC2 key pair |
| `InstanceProfileName` | An existing instance profile authorised for the build workflow |

The selected region needs at least two availability zones. Choose these values for your own account; the old laboratory identifiers are intentionally not included. The template does not create IAM roles, buckets, Lambdas, SNS, ECR, ECS or ALB resources. It has been parsed locally, not deployed or validated by AWS here.

## 2. S3 stages and Lambda configuration

Create separate, globally unique buckets. Block public access. Use one raw input bucket and the five configured output/state buckets below.

| Handler | Trigger bucket | Required environment variables | Output |
| --- | --- | --- | --- |
| `deduplicate.lambda_handler` | Raw input | `CLEAN_BUCKET` | `output_diasDuplicados.csv` |
| `weekly.lambda_handler` | Clean | `WEEKLY_MONTHLY_BUCKET`, `WEEKLY_ALERTS_BUCKET` | `outputSemanas.csv` in both buckets |
| `monthly.lambda_handler` | Weekly/monthly | `MONTHLY_BUCKET` | `datos_procesados.csv` |
| `alerts.lambda_handler` | Weekly/alerts | `STATE_BUCKET`, `SNS_TOPIC_NAME` | SNS message and `estado-alertas.csv` |

Package each corresponding Python file from `lambdas/` at the root of its Lambda ZIP. Configure a Python runtime with boto3, execution roles, CloudWatch logging, S3 object-created notifications, and Lambda permissions for S3 invocation. Filter notifications to `.csv` files. Use separate input/output buckets to avoid recursion.

Grant only the required S3 object reads/writes to each role. Alerts additionally need `sns:ListTopics` (the handler uses pagination) and `sns:Publish` for the configured topic. If email subscriptions are used, their recipients must confirm them independently. This preparation has not created subscriptions or sent messages.

For an academic demonstration, serialise uploads to reduce concurrent CSV updates. This does not turn the design into an exactly-once pipeline; see the architecture notes.

## 3. Container and ECR

Build from the repository root:

```bash
docker build -t aquasensecloud-api ./api
```

After creating your ECR repository, the following Bash sequence publishes the image to **your** account. Set `AWS_REGION` first:

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPOSITORY=aquasensecloud-api
REGISTRY="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker tag aquasensecloud-api:latest "$REGISTRY/$ECR_REPOSITORY:latest"
docker push "$REGISTRY/$ECR_REPOSITORY:latest"
```

The credentials used by the CLI belong in your AWS profile/session. Do not copy them into the Dockerfile, source files or repository.

## 4. ECS and load balancer

Create an ECS cluster, task definition and service compatible with your AWS/laboratory account. Configure:

- The ECR image and container port `5000`.
- `MONTHLY_BUCKET`, optional `MONTHLY_KEY`, and `AWS_REGION` environment variables.
- A task role with `s3:GetObject` for the monthly CSV, separate from the execution role used to pull images and write logs.
- An ALB target group pointing to port 5000 and health-check path `/health`.
- The ALB security group for inbound HTTP and the task security group for traffic from that ALB only.
- Task networking that can reach ECR, S3 and logs. In the original public-subnet design this requires suitable public addressing; alternative private networking needs its own routes/endpoints.

`/health` confirms application responsiveness only. Validate `/temp`, `/sd` and `/maxdiff` separately after uploading the synthetic sample to the raw bucket.

## 5. Verification and teardown

Check each intermediate CSV, the monthly API values and the alert-state CSV. Use a test SNS subscription you control if testing delivery. Inspect CloudWatch errors before retrying uploads. When finished, remove billable resources and any data you no longer need. Review retained buckets/images separately; deleting the partial CloudFormation stack does not remove resources created manually.
