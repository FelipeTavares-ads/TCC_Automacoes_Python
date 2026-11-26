"""Gera hub/hub.html: a pagina do hub com todos os arquivos do pacote
embutidos (base64), pronta para publicar.

Uso:  python construir_hub.py
Rode de novo sempre que um script de automacao mudar.
"""

from __future__ import annotations

import ast
import base64
import json
import os
import sys
from datetime import date
from pathlib import Path

HUB = Path(__file__).resolve().parent
PROJETO = HUB.parent

# Onde ficam os scripts do Medallia, PEC e PL (pasta do OneDrive).
ONEDRIVE_AUTOMACAO = Path(
    os.environ.get("HUB_FONTE_ONEDRIVE")
    or (
        Path(os.environ["OneDriveCommercial"])
        / "dashboards" / "Teste Python" / "automacao"
        if os.environ.get("OneDriveCommercial")
        else Path(
            r"C:\Users\felipe.jesus\OneDrive - Maria Selma Souza Alves "
            r"& Cia Ltda\dashboards\Teste Python\automacao"
        )
    )
)

SCRIPTS_PROJETO = ["teste_playwright.py"]
SCRIPTS_ONEDRIVE = [
    "automacao_pec_envio_er.py",
    "automacao_plataforma_logistica.py",
    "nps2.py",
    "satisfacao_revendedor_vd.py",
]

LEIAME = """HUB DE AUTOMACOES
=================

COMO USAR (e so isso)
---------------------
1. Descompacte este zip: botao direito > Extrair tudo.
   Escolha um lugar fixo, por exemplo a pasta Documentos.
2. Dentro da pasta, de dois cliques em  INICIAR.bat
3. Na primeira vez ele prepara o computador (alguns minutos) e pede o seu
   login da Extranet e/ou do Medallia. Fica salvo so neste computador.
4. O Chrome abre sozinho e baixa as planilhas. Nao mexa nele ate terminar.
5. No fim, a pasta com as planilhas abre sozinha. Elas ficam na pasta
   "saida", uma subpasta para cada vez que voce rodou.

Nao precisa abrir nem mexer na pasta "programa". Ela guarda o que faz o
hub funcionar.

PRECISA TER
-----------
- Windows e Google Chrome instalados.
- Acesso a internet e ao seu login corporativo.

SE ALGO DER ERRO
----------------
Abra a pasta "saida", entre na subpasta mais recente e envie o arquivo
log.txt para quem mantem o hub.

PARA BAIXAR OUTRO PERIODO
-------------------------
Volte ao hub, gere um novo pacote com o periodo desejado e repita.
"""


def ler_constantes_config() -> tuple[str, list[str]]:
    """Le URL_LOGIN e LOJAS_MEDALLIA do config.py original (fonte unica)."""
    fonte = (ONEDRIVE_AUTOMACAO / "config.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)

    valores = {}
    for no in arvore.body:
        if isinstance(no, ast.Assign) and len(no.targets) == 1:
            alvo = no.targets[0]
            if isinstance(alvo, ast.Name) and alvo.id in (
                "URL_LOGIN",
                "LOJAS_MEDALLIA",
            ):
                valores[alvo.id] = ast.literal_eval(no.value)

    return valores["URL_LOGIN"], valores["LOJAS_MEDALLIA"]


def montar_arquivos() -> dict[str, bytes]:
    arquivos: dict[str, bytes] = {}

    for nome in SCRIPTS_PROJETO:
        arquivos[nome] = (PROJETO / nome).read_bytes()

    for nome in SCRIPTS_ONEDRIVE:
        arquivos[nome] = (ONEDRIVE_AUTOMACAO / nome).read_bytes()

    pacote = HUB / "pacote"

    url_login, lojas = ler_constantes_config()
    config = (pacote / "config.py").read_text(encoding="utf-8")
    config = config.replace("__URL_LOGIN__", repr(url_login))
    config = config.replace("__LOJAS_MEDALLIA__", repr(lojas))
    arquivos["config.py"] = config.encode("utf-8")

    for nome in ("executar_hub.py", "requirements_hub.txt"):
        arquivos[nome] = (pacote / nome).read_bytes()

    # .bat precisa de CRLF para o cmd.exe do Windows.
    bat = (pacote / "rodar.bat").read_text(encoding="utf-8")
    bat = bat.replace("\r\n", "\n").replace("\n", "\r\n")
    arquivos["rodar.bat"] = bat.encode("utf-8")

    arquivos["LEIAME.txt"] = LEIAME.replace("\n", "\r\n").encode("utf-8")

    # Estrutura final do zip: so INICIAR.bat e LEIAME.txt ficam a vista;
    # o resto vai para a pasta "programa".
    topo = {"rodar.bat": "INICIAR.bat", "LEIAME.txt": "LEIAME.txt"}
    final: dict[str, bytes] = {}
    for nome, conteudo in arquivos.items():
        final[topo.get(nome, "programa/" + nome)] = conteudo

    return final


def main() -> int:
    arquivos = montar_arquivos()

    embutidos = {
        nome: base64.b64encode(conteudo).decode("ascii")
        for nome, conteudo in arquivos.items()
    }

    modelo = (HUB / "hub_modelo.html").read_text(encoding="utf-8")
    modelo = modelo.replace("__VERSAO__", date.today().isoformat())
    html = modelo.replace("__ARQUIVOS_JSON__", json.dumps(embutidos))

    saida = HUB / "hub.html"
    saida.write_text(html, encoding="utf-8")

    # Versao independente: arquivo unico, abre em qualquer navegador, com a
    # biblioteca de zip embutida (sem depender de CDN).
    tag_cdn = (
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/'
        '3.10.1/jszip.min.js"></script>'
    )
    assert tag_cdn in html
    jszip = (HUB / "vendor" / "jszip.min.js").read_text(encoding="utf-8")
    assert "</script" not in jszip.lower()
    html_unico = html.replace(tag_cdn, "<script>" + jszip + "</script>", 1)

    corte = html_unico.index('<div class="wrap">')
    cabecalho, corpo = html_unico[:corte], html_unico[corte:]
    cabeca_doc = '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>:root{color-scheme:light}body{margin:0}[hidden]{display:none!important}</style>'
    documento = cabeca_doc + cabecalho + '</head><body>' + corpo + '</body></html>'
    independente = HUB / "hub_automacoes.html"
    independente.write_text(documento, encoding="utf-8")
    print(
        f"Independente: {independente} "
        f"({independente.stat().st_size / 1024:.0f} KB)"
    )

    total = sum(len(c) for c in arquivos.values())
    print(f"Arquivos no pacote: {len(arquivos)} ({total / 1024:.0f} KB)")
    for nome in arquivos:
        print(f"  - {nome}")
    print(f"Gerado: {saida} ({saida.stat().st_size / 1024:.0f} KB)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
