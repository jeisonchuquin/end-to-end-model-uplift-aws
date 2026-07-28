'''
Entrena el modelo de UPLIFT

Ver notebooks/01_data_analisis_modelizacion.ipynb para el desarrollo completo, el chequeo
de balance de covariables, y la interpretación de negocio.
'''

import argparse
import json
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

FEATURES_NUMERICAS_BASELINE = ["feat_frecuencia_mensual", "feat_monto_mensual"]

FEATURES_NUMERICAS_COMPLETAS = FEATURES_NUMERICAS_BASELINE + [
    "feat_pct_compra_tarjeta",
    "feat_n_categorias_comercio",
    "feat_n_interacciones_marketing",
    "feat_tasa_respuesta_marketing",
    "feat_edad",
    "feat_antiguedad_dias",
]
FEATURES_CATEGORICAS_COMPLETAS = ["feat_ciudad", "feat_canal_adquisicion"]


CORTE = pd.Timestamp("2026-05-01")
PRE_INICIO = pd.Timestamp("2026-03-01")
POST_FIN = pd.Timestamp("2026-07-01")

TRATAMIENTO, CONTROL = 1, 0
UMBRAL_ALERTA_SMD = 0.25  # por encima de esto, la balance de covariables es "grande" (regla de Cohen/Austin)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--cliente-360", type=str, default=None)
    p.add_argument("--transacciones", type=str, default=None)
    p.add_argument("--model-dir", type=str, default=None)
    p.add_argument("--test-size", type=float, default=0.25)
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument("--n-estimators", type=int, default=300)
    p.add_argument("--max-depth", type=int, default=8)
    p.add_argument("--wandb-project", type=str, default="end-to-end-model-uplift-aws")
    p.add_argument("--no-wandb", action="store_true")
    return p.parse_args()


def repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def construir_panel(cliente_360: pd.DataFrame, transacciones: pd.DataFrame) -> pd.DataFrame:
    '''
    Panel tratado(fisica_activa)/control(solo_virtual) alrededor de una fecha de
    corte COMÚN a ambos brazos, necesario porque el control nunca tiene una fecha
    de activación propia. 
    
    Target: `aumento_uso` = 1 si la frecuencia mensual de transacciones subió de la ventana pre-corte a la post-corte.
    '''
    
    panel_clientes = cliente_360[cliente_360["grupo_piloto"].isin(["fisica_activa", "solo_virtual"])].copy()
    panel_clientes["fecha_registro"] = pd.to_datetime(panel_clientes["fecha_registro"])
    
    # exige historial en ambas ventanas
    panel_clientes = panel_clientes[panel_clientes["fecha_registro"] < PRE_INICIO]
    panel_clientes["tratado"] = np.where(panel_clientes["grupo_piloto"] == "fisica_activa", TRATAMIENTO, CONTROL)

    tx = transacciones[
        transacciones["cliente_id"].isin(panel_clientes["cliente_id"])
        & (transacciones["fecha"] >= PRE_INICIO)
        & (transacciones["fecha"] < POST_FIN)
    ].copy()
    tx["periodo"] = np.where(tx["fecha"] < CORTE, "pre", "post")
    conteo = tx.groupby(["cliente_id", "periodo"]).size().unstack(fill_value=0).reindex(columns=["pre", "post"], fill_value=0)

    panel = panel_clientes.set_index("cliente_id").join(conteo, how="left")
    panel[["pre", "post"]] = panel[["pre", "post"]].fillna(0)
    panel["aumento_uso"] = (panel["post"] > panel["pre"]).astype(int)
    return panel


def chequear_balance_covariables(panel: pd.DataFrame, features_numericas: list) -> pd.DataFrame:
    '''
    Standardized Mean Difference (SMD) tratado-vs-control por feature para ver si 
    hace falta Propensity Score Matching
    '''
    
    tratado = panel[panel["tratado"] == TRATAMIENTO]
    control = panel[panel["tratado"] == CONTROL]

    filas = []
    for col in features_numericas:
        a, b = tratado[col].dropna(), control[col].dropna()
        pooled_std = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
        smd = (a.mean() - b.mean()) / pooled_std if pooled_std > 0 else np.nan
        filas.append({"feature": col, "media_tratado": a.mean(), "media_control": b.mean(), "smd": smd})

    tabla = pd.DataFrame(filas)
    desbalanceadas = tabla[tabla["smd"].abs() > UMBRAL_ALERTA_SMD]
    
    if len(desbalanceadas):
        print(f"ADVERTENCIA: {len(desbalanceadas)} features con |SMD| > {UMBRAL_ALERTA_SMD} pese a "
              f"asignación aleatoria confirmada -- considerar Propensity Score Matching:")
        print(desbalanceadas.to_string(index=False))
    
    else:
        print(f"Balance de covariables OK (todas las |SMD| <= {UMBRAL_ALERTA_SMD}) -- "
              f"consistente con asignación aleatoria, no se aplica Propensity Score Matching.")
    
    return tabla


def construir_preprocesador() -> ColumnTransformer:
    
    return ColumnTransformer([
        ("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]), FEATURES_NUMERICAS_COMPLETAS),
        ("cat", Pipeline([
            ("imputer", SimpleImputer(strategy="constant", fill_value="desconocido")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]), FEATURES_CATEGORICAS_COMPLETAS),
    ])


def main():
    
    from causalml.inference.meta import BaseTClassifier

    args = parse_args()
    base = repo_root()
    cliente_360_path = args.cliente_360 or f"{base}/data/curated/cliente_360"
    transacciones_path = args.transacciones or f"{base}/data/processed/transacciones"
    model_dir = args.model_dir or f"{base}/models/uplift"
    os.makedirs(model_dir, exist_ok=True)

    cliente_360 = pd.read_parquet(cliente_360_path)
    transacciones = pd.read_parquet(transacciones_path)
    transacciones["fecha"] = pd.to_datetime(transacciones["fecha"])

    panel = construir_panel(cliente_360, transacciones)
    cols = FEATURES_NUMERICAS_COMPLETAS + FEATURES_CATEGORICAS_COMPLETAS
    panel = panel.dropna(subset=FEATURES_NUMERICAS_COMPLETAS)
    print(f"Panel: {len(panel):,} clientes (tratado={int((panel['tratado']==TRATAMIENTO).sum()):,}, "
          f"control={int((panel['tratado']==CONTROL).sum()):,})")

    tabla_smd = chequear_balance_covariables(panel, FEATURES_NUMERICAS_COMPLETAS)

    train_df, test_df = train_test_split(
        panel, test_size=args.test_size, random_state=args.random_state, stratify=panel[["tratado", "aumento_uso"]]
    )

    preprocesador = construir_preprocesador()
    X_train = preprocesador.fit_transform(train_df[cols])
    X_test = preprocesador.transform(test_df[cols])
    treatment_train = train_df["tratado"].to_numpy()
    treatment_test = test_df["tratado"].to_numpy()
    y_train = train_df["aumento_uso"].to_numpy()
    y_test = test_df["aumento_uso"].to_numpy()

    base_learner = RandomForestClassifier(
        n_estimators=args.n_estimators, max_depth=args.max_depth, class_weight="balanced",
        random_state=args.random_state, n_jobs=-1,
    )
    learner = BaseTClassifier(learner=base_learner, control_name=CONTROL)
    learner.fit(X=X_train, treatment=treatment_train, y=y_train)

    
    mask_c_test = treatment_test == CONTROL
    mask_t_test = treatment_test == TRATAMIENTO
    auc_control = roc_auc_score(
        y_test[mask_c_test], learner.models_c[TRATAMIENTO].predict_proba(X_test[mask_c_test])[:, 1]
    )
    auc_tratamiento = roc_auc_score(
        y_test[mask_t_test], learner.models_t[TRATAMIENTO].predict_proba(X_test[mask_t_test])[:, 1]
    )

    tau_test = learner.predict(X=X_test).ravel()
    ate, ate_lb, ate_ub = learner.estimate_ate(X=X_test, treatment=treatment_test, y=y_test)

    import causalml.metrics as causalml_metrics

    
    df_qini = pd.DataFrame({"y": y_test, "w": treatment_test, "T-Learner": tau_test})
    qini = causalml_metrics.qini_score(df_qini, outcome_col="y", treatment_col="w")

    metricas = {
        "n_train": len(train_df),
        "n_test": len(test_df),
        "auc_control": float(auc_control),
        "auc_tratamiento": float(auc_tratamiento),
        "ate": float(np.ravel(ate)[0]),
        "ate_lb": float(np.ravel(ate_lb)[0]),
        "ate_ub": float(np.ravel(ate_ub)[0]),
        "qini_score": float(qini["T-Learner"]),
        "tasa_aumento_control": float(y_test[mask_c_test].mean()),
        "tasa_aumento_tratamiento": float(y_test[mask_t_test].mean()),
    }
    print(json.dumps(metricas, indent=2))

    if not args.no_wandb:
        import wandb

        run = wandb.init(project=args.wandb_project, job_type="training", name="uplift-t-learner-causalml")
        wandb.log(metricas)
        wandb.log({"balance_covariables": wandb.Table(dataframe=tabla_smd)})
        run.finish()

    joblib.dump(
        {
            "learner": learner,
            "preprocesador": preprocesador,
            "features_numericas": FEATURES_NUMERICAS_COMPLETAS,
            "features_categoricas": FEATURES_CATEGORICAS_COMPLETAS,
            "control_name": CONTROL,
            "treatment_name": TRATAMIENTO,
        },
        os.path.join(model_dir, "modelo_uplift_tlearner.joblib"),
    )
    with open(os.path.join(model_dir, "metricas_uplift.json"), "w", encoding="utf-8") as f:
        json.dump(metricas, f, indent=2)
    tabla_smd.to_csv(os.path.join(model_dir, "balance_covariables.csv"), index=False)

    print(f"\nModelo y métricas guardados en {model_dir}")


if __name__ == "__main__":
    main()
