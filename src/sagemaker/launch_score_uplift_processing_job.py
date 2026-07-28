'''
Lanza el SCORING de la población solo_virtual, i.e. candidatos de la siguiente ola
como un SageMaker Processing Job, usando el modelo ya entrenado por
launch_uplift_processing_job.py y leído desde `s3://<bucket>/models/uplift/.

Escribe:
    - S3 particionado por fecha (`s3://<bucket>/predictions/uplift_scores/dt=<fecha>/`),
    fuente de auditoría para la tabla Glue `predictions.uplift_scores`.
    - DynamoDB (`--dynamodb-table`), capa de serving de baja latencia para el Lambda.
'''

import argparse
import os
from datetime import date, datetime

import boto3

SKLEARN_FRAMEWORK_VERSION = "1.2-1"
CODE_DIR_CONTENEDOR = "/opt/ml/processing/code_extra"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--bucket", required=True)
    p.add_argument("--role-arn", required=True)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--instance-type", default="ml.m5.xlarge")
    p.add_argument("--dynamodb-table", default=None,
                    help="si no se da, se omite el escrito a DynamoDB (solo S3/Glue)")
    p.add_argument("--fecha", default=None, help="YYYY-MM-DD, default hoy")
    return p.parse_args()


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def main():
    args = parse_args()
    fecha = args.fecha or date.today().isoformat()

    import sagemaker
    from sagemaker.processing import ProcessingInput, ProcessingOutput
    from sagemaker.sklearn.processing import SKLearnProcessor

    session = sagemaker.Session(boto3.Session(region_name=args.region))

    env = {"AWS_REGION": args.region}
    if args.dynamodb_table:
        env["DYNAMODB_TABLE"] = args.dynamodb_table

    processor = SKLearnProcessor(
        framework_version=SKLEARN_FRAMEWORK_VERSION,
        role=args.role_arn,
        instance_count=1,
        instance_type=args.instance_type,
        command=["/bin/bash"],
        sagemaker_session=session,
        base_job_name="peigo-uplift-scoring",
        env=env,
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
            source=f"s3://{args.bucket}/models/uplift/",
            destination="/opt/ml/processing/input/modelo",
            input_name="modelo",
        ),
    ]
    outputs = [
        ProcessingOutput(
            source="/opt/ml/processing/output/predictions",
            destination=f"s3://{args.bucket}/predictions/uplift_scores/dt={fecha}/",
            output_name="predicciones",
        ),
    ]

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    job_name = f"peigo-uplift-scoring-{timestamp}"
    print(f"Lanzando Processing Job: {job_name}")

    script_absoluto = f"{os.path.dirname(os.path.abspath(__file__))}/run_score_uplift_job.sh"
    code_path = os.path.relpath(script_absoluto, os.getcwd())

    processor.run(
        code=code_path,
        inputs=inputs,
        outputs=outputs,
        job_name=job_name,
        wait=True,
        logs=True,
    )

    print(f"\nProcessing Job completo. Predicciones en "
          f"s3://{args.bucket}/predictions/uplift_scores/dt={fecha}/")


if __name__ == "__main__":
    main()
