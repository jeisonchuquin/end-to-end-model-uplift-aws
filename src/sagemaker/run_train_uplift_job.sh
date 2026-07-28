#!/bin/bash
# Bootstrap del SageMaker Processing Job (ver launch_uplift_processing_job.py).
set -euo pipefail

CODE_DIR="/opt/ml/processing/code_extra"
VENV_DIR="/tmp/uplift-venv"

echo "Creando venv limpio para causalml (Python 3.9 del contenedor, aislado del resto)..."
python -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

echo "Instalando dependencias de causalml (requirements-uplift-container.txt)..."
pip install --quiet --upgrade pip
pip install --quiet -r "${CODE_DIR}/src/sagemaker/requirements-uplift-container.txt"

ARGS=(
    --cliente-360 /opt/ml/processing/input/cliente_360
    --transacciones /opt/ml/processing/input/transacciones
    --model-dir /opt/ml/processing/output/model
)

if [ -z "${WANDB_API_KEY:-}" ]; then
    echo "WANDB_API_KEY no seteada -- se entrena sin logging a W&B."
    ARGS+=(--no-wandb)
fi

echo "Entrenando T-learner de uplift (causalml)..."
python "${CODE_DIR}/src/sagemaker/train_uplift.py" "${ARGS[@]}"
