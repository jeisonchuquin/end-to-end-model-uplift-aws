import numpy as np
import pandas as pd

from src.sagemaker.train_uplift import CONTROL, TRATAMIENTO, chequear_balance_covariables, construir_panel


def test_construir_panel_marca_aumento_uso_correctamente():
    cliente_360 = pd.DataFrame({
        "cliente_id": ["c1", "c2", "c3"],
        "grupo_piloto": ["fisica_activa", "solo_virtual", "fisica_activa"],
        "fecha_registro": ["2026-01-01", "2026-01-01", "2026-01-01"],
    })
    transacciones = pd.DataFrame({
        "cliente_id": ["c1", "c1", "c1", "c2", "c3"],
        "fecha": pd.to_datetime([
            "2026-03-15",  # c1 pre
            "2026-05-15", "2026-05-20",  # c1 post (2 > 1 -> aumento)
            "2026-03-10",  # c2 pre, sin post -> no aumento
            "2026-06-01",  # c3 post, sin pre -> aumento (0 -> 1)
        ]),
    })

    panel = construir_panel(cliente_360, transacciones).reset_index()

    assert set(panel["tratado"]) == {TRATAMIENTO, CONTROL}
    assert int(panel.loc[panel["cliente_id"] == "c1", "aumento_uso"].iloc[0]) == 1
    assert int(panel.loc[panel["cliente_id"] == "c2", "aumento_uso"].iloc[0]) == 0
    assert int(panel.loc[panel["cliente_id"] == "c3", "aumento_uso"].iloc[0]) == 1


def test_construir_panel_excluye_clientes_registrados_tarde():
    cliente_360 = pd.DataFrame({
        "cliente_id": ["c1"],
        "grupo_piloto": ["fisica_activa"],
        "fecha_registro": ["2026-04-01"],  # despues de PRE_INICIO (2026-03-01)
    })
    transacciones = pd.DataFrame({"cliente_id": [], "fecha": pd.to_datetime([])})

    panel = construir_panel(cliente_360, transacciones)
    assert len(panel) == 0


def test_chequear_balance_covariables_detecta_desbalance_grande():
    rng = np.random.default_rng(0)
    panel = pd.DataFrame({
        "tratado": [TRATAMIENTO] * 50 + [CONTROL] * 50,
        "feat_x": list(rng.normal(10, 1, 50)) + list(rng.normal(0, 1, 50)),
    })
    tabla = chequear_balance_covariables(panel, ["feat_x"])
    assert abs(tabla.loc[tabla["feature"] == "feat_x", "smd"].iloc[0]) > 0.25


def test_chequear_balance_covariables_ok_si_medias_similares():
    rng = np.random.default_rng(0)
    panel = pd.DataFrame({
        "tratado": [TRATAMIENTO] * 50 + [CONTROL] * 50,
        "feat_x": list(rng.normal(0, 1, 100)),
    })
    tabla = chequear_balance_covariables(panel, ["feat_x"])
    assert abs(tabla.loc[tabla["feature"] == "feat_x", "smd"].iloc[0]) < 0.25
