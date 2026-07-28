'''
Lanza el entrenamiento del T-learner de uplift como un SageMaker **Processing Job** 
'''

import argparse
import os
from datetime import datetime

import boto3

SKLEARN_FRAMEWORK_VERSION = "1.2-1"
CODE_DIR_CONTENEDOR = "/opt/ml/processing/code_extra"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--bucket", required=True)
    p.add_argument("--role-arn", required=True)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--instance-type", default="ml.m5.xlarge")
    return p.parse_args()


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def main():
    args = parse_args()

    import sagemaker
    from sagemaker.processing import ProcessingInput, ProcessingOutput
    from sagemaker.sklearn.processing import SKLearnProcessor

    session = sagemaker.Session(boto3.Session(region_name=args.region))

    processor = SKLearnProcessor(
        framework_version=SKLEARN_FRAMEWORK_VERSION,
        role=args.role_arn,
        instance_count=1,
        instance_type=args.instance_type,
        command=["/bin/bash"],
        sagemaker_session=session,
        base_job_name="peigo-uplift-training",
        env={"WANDB_API_KEY": os.environ.get("WANDB_API_KEY", "")},
    )

    src_relativo = os.path.relpath(f"{repo_root()}/src", os.getcwd())

    inputs = [
        ProcessingInput(
            source=src_relativo,
            destination=f"{CODE_DIR_CONTENEDOR}/src",
            input_name="src",
        ),
        ProcessingInput(
            source=f"s3://{args.bucket}/curated/cliente_360",
            destination="/opt/ml/processing/input/cliente_360",
            input_name="cliente_360",
        ),
        ProcessingInput(
            source=f"s3://{args.bucket}/processed/transacciones",
            destination="/opt/ml/processing/input/transacciones",
            input_name="transacciones",
        ),
    ]
    outputs = [
        ProcessingOutput(
            source="/opt/ml/processing/output/model",
            destination=f"s3://{args.bucket}/models/uplift/",
            output_name="modelo_uplift",
        ),
    ]

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    job_name = f"peigo-uplift-training-{timestamp}"
    print(f"Lanzando Processing Job: {job_name}")

    script_absoluto = f"{os.path.dirname(os.path.abspath(__file__))}/run_train_uplift_job.sh"
    code_path = os.path.relpath(script_absoluto, os.getcwd())

    processor.run(
        code=code_path,
        inputs=inputs,
        outputs=outputs,
        job_name=job_name,
        wait=True,
        logs=True,
    )

    print(f"\nProcessing Job completo. Modelo en s3://{args.bucket}/models/uplift/")
    print("Siguiente paso: descargar metricas_uplift.json de esa ruta para revisar "
          "ATE/Qini antes de correr score_uplift.py (o su propio Processing Job) sobre solo_virtual.")


if __name__ == "__main__":
    main()
