#!/bin/bash
# Bootstrap del SageMaker Processing Job de SCORING (ver launch_score_uplift_processing_job.py).
set -euo pipefail

CODE_DIR="/opt/ml/processing/code_extra"
VENV_DIR="/tmp/uplift-venv"

echo "Creando venv limpio para causalml (Python 3.9 del contenedor, aislado del resto)..."
python -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

echo "Instalando dependencias (requirements-uplift-container.txt + boto3 para DynamoDB)..."
pip install --quiet --upgrade pip
pip install --quiet -r "${CODE_DIR}/src/sagemaker/requirements-uplift-container.txt" boto3

ARGS=(
    --cliente-360 /opt/ml/processing/input/cliente_360
    --model-path /opt/ml/processing/input/modelo/modelo_uplift_tlearner.joblib
    --output-dir /opt/ml/processing/output/predictions
    --region "${AWS_REGION:-us-east-1}"
)

if [ -n "${DYNAMODB_TABLE:-}" ]; then
    ARGS+=(--dynamodb-table "${DYNAMODB_TABLE}")
fi

echo "Puntuando población solo_virtual..."
python "${CODE_DIR}/src/sagemaker/score_uplift.py" "${ARGS[@]}"
