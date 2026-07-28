from src.sagemaker.score_uplift import clasificar_segmento, razon_principal


def test_clasificar_segmento_persuadible():
    assert clasificar_segmento(p_tratamiento=0.8, p_control=0.2) == "persuadible"


def test_clasificar_segmento_sure_thing():
    assert clasificar_segmento(p_tratamiento=0.8, p_control=0.7) == "sure_thing"


def test_clasificar_segmento_lost_cause():
    assert clasificar_segmento(p_tratamiento=0.2, p_control=0.1) == "lost_cause"


def test_clasificar_segmento_sleeping_dog():
    assert clasificar_segmento(p_tratamiento=0.2, p_control=0.8) == "sleeping_dog"


def test_clasificar_segmento_umbral_inclusivo():
    # UMBRAL_SEGMENTO=0.5 con comparación ">=": exactamente 0.5 cuenta como "alto"
    assert clasificar_segmento(p_tratamiento=0.5, p_control=0.5) == "sure_thing"


def test_razon_principal_persuadible_menciona_ambas_probabilidades():
    razon = razon_principal("persuadible", p_tratamiento=0.9, p_control=0.3)
    assert "30%" in razon and "90%" in razon


def test_razon_principal_sleeping_dog_advierte_reduccion():
    razon = razon_principal("sleeping_dog", p_tratamiento=0.2, p_control=0.8)
    assert "REDUCIR" in razon
