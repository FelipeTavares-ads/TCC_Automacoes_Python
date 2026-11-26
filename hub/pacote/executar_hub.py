"""Executor do Hub de Automacoes.

Le configuracao.json (gerado pelo hub HTML), pede o login na primeira
vez, roda as automacoes escolhidas uma depois da outra e junta tudo em
saida/<data_hora>/. Pensado para quem nao usa terminal: so aparece texto
simples e, no fim, a pasta com os arquivos e aberta sozinha.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PASTA = Path(__file__).resolve().parent
ARQUIVO_CONFIG = PASTA / "configuracao.json"
ARQUIVO_ENV = PASTA / ".env"

# Indicadores que rodam dentro do teste_playwright.py (mesmo Chrome/login).
ETAPAS_EXTRANET = {
    "servicos_em_loja",
    "loja_digital",
    "treinamentos_forca_vendas",
    "treinamentos_iaf_ciclo",
    "id_cliente",
    "acao_de_fluxo",
    "programa_fidelidade",
    "canal_loja",
    "venda_direta",
}

# Indicador -> script proprio.
SCRIPTS_PROPRIOS = {
    "pec": ("automacao_pec_envio_er.py", "PEC (Envio ER)", "extranet"),
    "pl": (
        "automacao_plataforma_logistica.py",
        "Plataforma Logística",
        "extranet",
    ),
    "medallia_nps": ("nps2.py", "NPS (Medallia)", "medallia"),
    "medallia_satisfacao": (
        "satisfacao_revendedor_vd.py",
        "Satisfação do Revendedor (Medallia)",
        "medallia",
    ),
}

NOMES = {
    "servicos_em_loja": "Serviços em Loja",
    "loja_digital": "Loja Digital (TME)",
    "treinamentos_forca_vendas": "Treinamentos IAF Força de Vendas",
    "treinamentos_iaf_ciclo": "Treinamentos IAF por ciclo",
    "id_cliente": "ID Cliente",
    "acao_de_fluxo": "Ação de Fluxo",
    "programa_fidelidade": "Programa Fidelidade",
    "canal_loja": "Canal Loja",
    "venda_direta": "Venda Direta - Monitoramento de Base",
}

PADRAO_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def escrever(texto: str = "") -> None:
    print(texto, flush=True)


def ler_env() -> dict[str, str]:
    valores: dict[str, str] = {}

    if ARQUIVO_ENV.exists():
        for linha in ARQUIVO_ENV.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            valores[chave.strip()] = valor.strip()

    return valores


def salvar_env(valores: dict[str, str]) -> None:
    linhas = [f"{chave}={valor}" for chave, valor in valores.items()]
    ARQUIVO_ENV.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def garantir_credenciais(sistemas: set[str]) -> dict[str, str]:
    """Pede usuario/senha so do que falta e guarda no .env local."""
    valores = ler_env()
    pedidos = {
        "extranet": (
            "Extranet",
            "EXTRANET_USUARIO",
            "EXTRANET_SENHA",
        ),
        "medallia": ("Medallia", "BOTI_USUARIO", "BOTI_SENHA"),
    }

    alterou = False

    for sistema in ("extranet", "medallia"):
        if sistema not in sistemas:
            continue

        nome, chave_usuario, chave_senha = pedidos[sistema]

        if valores.get(chave_usuario) and valores.get(chave_senha):
            continue

        escrever()
        escrever(f"Primeiro acesso ao {nome}: informe seu login.")
        escrever("(Fica salvo só neste computador, na pasta do hub.)")

        valores[chave_usuario] = input(f"  Usuário do {nome}: ").strip()
        valores[chave_senha] = getpass.getpass(
            f"  Senha do {nome} (não aparece ao digitar): "
        )
        alterou = True

    if alterou:
        salvar_env(valores)

    return valores


def validar_config(config: dict) -> None:
    for campo in ("periodo_inicio", "periodo_fim"):
        valor = (config.get(campo) or "").strip()
        if valor and not PADRAO_DATA.match(valor):
            raise ValueError(
                f"{campo} deve estar no formato dd/mm/aaaa: {valor}"
            )

    if not config.get("indicadores"):
        raise ValueError("Nenhum indicador foi escolhido.")


def montar_ambiente(config: dict, credenciais: dict, saida: Path) -> dict:
    ambiente = os.environ.copy()
    ambiente.update(credenciais)
    ambiente["HUB_SAIDA"] = str(saida)
    ambiente["PYTHONIOENCODING"] = "utf-8"
    ambiente["PYTHONUNBUFFERED"] = "1"

    mapa = {
        "periodo_inicio": "PERIODO_INICIO",
        "periodo_fim": "PERIODO_FIM",
        "ciclo_inicio": "CICLO_INICIO",
        "ciclo_fim": "CICLO_FIM",
        "campanhas": "CAMPANHAS",
        "ers_vd": "ERS_VD",
    }

    for campo, variavel in mapa.items():
        valor = str(config.get(campo) or "").strip()
        if valor:
            ambiente[variavel] = valor
        else:
            ambiente.pop(variavel, None)

    return ambiente


def rodar(comando: list[str], ambiente: dict, log) -> int:
    processo = subprocess.Popen(
        comando,
        cwd=str(PASTA),
        env=ambiente,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert processo.stdout is not None

    for linha in processo.stdout:
        texto = linha.rstrip("\n")
        escrever("    " + texto)
        log.write(texto + "\n")
        log.flush()

    return processo.wait()


def main() -> int:
    escrever("=" * 60)
    escrever(" HUB DE AUTOMAÇÕES")
    escrever("=" * 60)

    if not ARQUIVO_CONFIG.exists():
        escrever("Arquivo configuracao.json não encontrado.")
        return 1

    config = json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
    validar_config(config)

    indicadores: list[str] = config["indicadores"]

    etapas = [i for i in indicadores if i in ETAPAS_EXTRANET]
    proprios = [i for i in indicadores if i in SCRIPTS_PROPRIOS]
    desconhecidos = [
        i for i in indicadores
        if i not in ETAPAS_EXTRANET and i not in SCRIPTS_PROPRIOS
    ]

    if desconhecidos:
        escrever(f"Indicadores desconhecidos: {desconhecidos}")
        return 1

    sistemas: set[str] = set()
    if etapas:
        sistemas.add("extranet")
    for chave in proprios:
        sistemas.add(SCRIPTS_PROPRIOS[chave][2])

    credenciais = garantir_credenciais(sistemas)

    saida = PASTA.parent / "saida" / datetime.now().strftime("%Y-%m-%d_%H%M")
    saida.mkdir(parents=True, exist_ok=True)

    ambiente = montar_ambiente(config, credenciais, saida)

    escrever()
    escrever("Resumo do que vai rodar:")
    for chave in indicadores:
        nome = NOMES.get(chave) or SCRIPTS_PROPRIOS[chave][1]
        escrever(f"  - {nome}")
    if config.get("periodo_inicio") or config.get("periodo_fim"):
        escrever(
            f"  Período: {config.get('periodo_inicio') or '(padrão)'}"
            f" a {config.get('periodo_fim') or '(padrão)'}"
        )
    if config.get("ciclo_inicio"):
        escrever(
            f"  Ciclos: {config['ciclo_inicio']}"
            f" a {config.get('ciclo_fim') or config['ciclo_inicio']}"
        )
    if config.get("campanhas"):
        escrever(f"  Campanhas: {config['campanhas']}")
    escrever()
    escrever("O Chrome vai abrir sozinho. Não mexa nele até terminar.")
    escrever()

    resultados: list[tuple[str, bool]] = []

    with open(saida / "log.txt", "w", encoding="utf-8") as log:
        trabalhos: list[tuple[str, list[str], dict]] = []

        if etapas:
            ambiente_extranet = dict(ambiente)
            ambiente_extranet["ETAPAS"] = ",".join(etapas)
            trabalhos.append(
                (
                    "Indicadores da Extranet",
                    [sys.executable, "-u", "teste_playwright.py"],
                    ambiente_extranet,
                )
            )

        for chave in proprios:
            script, nome, _ = SCRIPTS_PROPRIOS[chave]
            trabalhos.append(
                (nome, [sys.executable, "-u", script], ambiente)
            )

        for indice, (nome, comando, env) in enumerate(trabalhos, start=1):
            escrever("-" * 60)
            escrever(f" [{indice}/{len(trabalhos)}] {nome}")
            escrever("-" * 60)
            log.write(f"\n===== {nome} =====\n")

            codigo = rodar(comando, env, log)
            resultados.append((nome, codigo == 0))

            escrever(
                "  -> concluído" if codigo == 0
                else f"  -> terminou com erro (código {codigo})"
            )
            escrever()

    linhas = ["RESULTADO", "=" * 40]
    for nome, ok in resultados:
        linhas.append(f"{'OK    ' if ok else 'ERRO  '}{nome}")
    linhas.append("")
    linhas.append(f"Arquivos em: {saida}")
    linhas.append("Se algo deu erro, mande o arquivo log.txt desta pasta.")
    (saida / "RESUMO.txt").write_text("\n".join(linhas), encoding="utf-8")

    escrever("=" * 60)
    escrever("\n".join(linhas))
    escrever("=" * 60)

    try:
        os.startfile(str(saida))  # type: ignore[attr-defined]
    except Exception:
        pass

    return 0 if all(ok for _, ok in resultados) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        escrever(f"Erro: {erro}")
        sys.exit(1)
