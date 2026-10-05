# Source and publication preparation

Source: the uploaded `SubidoGithubProyectoV2_GMV(1).zip`, project folder `ProyectoV2`. The original archive is unchanged. No original Git history was present.

## Changes in this edition

- Organised the five Python modules into `api/` and `lambdas/`, with descriptive importable handler names.
- Replaced fixed bucket/topic names with required environment variables.
- Fixed monthly reload of prior results: CSV `anio` becomes internal `year`, and numeric values are parsed before sorting/subtraction.
- Decoded URL-encoded S3 object keys in weekly and monthly handlers.
- Made missing SNS topics fail before marking an alert as sent; added topic-list pagination.
- Propagated state/deduplication access errors instead of treating every error as an empty dataset.
- Disabled Flask debugging; added a Python 3.12/Gunicorn Docker image and updated dependency ranges. These are not a locked environment.
- Parameterised the network template's AMI, key pair, instance profile and admin CIDR; selected availability zones from the deployment region; enabled the Docker service during bootstrap.
- Added documentation, shared authorship, MIT licence, synthetic data and eight offline regression tests.

The calculation rules are retained except for the monthly reload correction. Outstanding cross-month weighting and concurrency limitations are documented, not silently represented as complete.

## Excluded material

- The assignment PDF and full laboratory report: replaced by focused documentation without account-specific screenshots or identifiers.
- `comandosAWSCLI.txt`: replaced by the deployment guide, with account details removed and password-stdin used for ECR login.
- Original CSV snapshots, duplicate weekly output and alert-delivery state: replaced by a small synthetic fixture with known expected results. This avoids presenting old state as a clean starting point or assuming redistribution rights for the source dataset.

## Validation

Eight offline tests passed under Python 3.12 with simulated S3/SNS. No AWS calls, paid deployment, real SNS notifications or model training were performed. Docker/CloudFormation have not been runtime-tested in AWS.
