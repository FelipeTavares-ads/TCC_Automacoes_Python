"""Configuracao enxuta do hub (usada pelo nps2.py).

Gerada a partir do config.py original; aqui nao ha dependencia das
planilhas de IAF, entao funciona em qualquer maquina.
"""

import os
from pathlib import Path

BASE = Path(__file__).resolve().parent

PASTA_SAIDA = Path(os.environ.get("HUB_SAIDA") or (BASE / "saida"))
PASTA_BRUTOS = PASTA_SAIDA / "dados_brutos"
ARQUIVO_NPS = PASTA_BRUTOS / "nps.xlsx"
LOG = PASTA_SAIDA / "log_nps.txt"

USUARIO = os.environ.get("BOTI_USUARIO")
SENHA = os.environ.get("BOTI_SENHA")

URL_LOGIN = __URL_LOGIN__

LOJAS_MEDALLIA = __LOJAS_MEDALLIA__


def validar_credenciais():
    if not USUARIO or not SENHA:
        raise RuntimeError(
            "Credenciais do Medallia nao configuradas "
            "(BOTI_USUARIO / BOTI_SENHA)."
        )
