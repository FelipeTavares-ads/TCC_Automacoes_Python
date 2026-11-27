"""Painel local de automacoes.

Sobe um servidor SO neste computador (127.0.0.1), abre o painel no
navegador e roda as automacoes escolhidas, uma depois da outra, mostrando
o log ao vivo. Usa os mesmos scripts, pastas e logins de sempre.

Uso: de dois cliques em abrir_painel.bat (e deixe a janela aberta).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import consolidacao
import fechamento

# O painel fica no computador de quem usa (Downloads\automacao_extranet\
# automacao_extranet\painel), junto do teste_playwright.py (Extranet). Os
# scripts ficam na pasta "automacao" do OneDrive, compartilhada.
PAINEL = Path(__file__).resolve().parent
PROJETO = PAINEL.parent

# .env local de quem usa (%LOCALAPPDATA%\automacao_gms\.env): logins e, se
# preciso, AUTOMACAO_PASTA (onde está a pasta do OneDrive neste computador).
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "automacao_gms"
try:
    from dotenv import load_dotenv

    load_dotenv(os.environ.get("AUTOMACAO_ENV") or LOCAL / ".env")
except ImportError:
    pass


def _pasta_automacao() -> Path:
    """A pasta "automacao" (com caminhos.py), sem caminho fixo de máquina."""
    candidatos = [os.environ.get("AUTOMACAO_PASTA")]
    if os.environ.get("OneDriveCommercial"):
        candidatos.append(
            Path(os.environ["OneDriveCommercial"]) / "dashboards" / "Teste Python" / "automacao"
        )
    candidatos.append(PROJETO)  # painel guardado dentro da própria pasta
    for candidato in candidatos:
        if candidato and (Path(candidato) / "caminhos.py").is_file():
            return Path(candidato)
    raise SystemExit(
        "Não achei a pasta da automação no OneDrive (a que tem caminhos.py).\n"
        f"Coloque no arquivo {LOCAL / '.env'} a linha:\n"
        "  AUTOMACAO_PASTA=C:\\caminho\\completo\\ate\\automacao"
    )


ONEDRIVE = _pasta_automacao()
sys.path.insert(0, str(ONEDRIVE))
import caminhos  # noqa: E402  (logins e perfis de quem roda, fora do OneDrive)

PORTA = int(os.environ.get("PAINEL_PORTA", "8765"))
TOKEN = secrets.token_urlsafe(16)
PASTA_LOGS = PAINEL / "logs"
QUEM = os.environ.get("USERNAME") or "usuario"

# id -> (nome, tipo, script, pasta de execucao, sistema)
# tipo "etapa" roda dentro do teste_playwright.py (um Chrome, um login).
CATALOGO = {
    "canal_loja": ("Canal Loja (IAF de loja)", "etapa", None, None, "extranet"),
    "servicos_em_loja": ("Serviços em Loja", "etapa", None, None, "extranet"),
    "loja_digital": ("Loja Digital (TME)", "etapa", None, None, "extranet"),
    "id_cliente": ("ID Cliente", "etapa", None, None, "extranet"),
    "programa_fidelidade": (
        "Programa Fidelidade", "etapa", None, None, "extranet",
    ),
    "acao_de_fluxo": ("Ação de Fluxo", "etapa", None, None, "extranet"),
    "venda_direta": (
        "Venda Direta - Monitoramento de Base",
        "etapa", None, None, "extranet",
    ),
    "pec": (
        "PEC (Envio ER)", "script",
        "automacao_pec_envio_er.py", ONEDRIVE, "extranet",
    ),
    "pl": (
        "Plataforma Logística", "script",
        "automacao_plataforma_logistica.py", ONEDRIVE, "extranet",
    ),
    "medallia_nps": (
        "NPS por loja (Medallia)", "script", "nps2.py", ONEDRIVE, "medallia",
    ),
    "medallia_satisfacao": (
        "Satisfação do Revendedor (Medallia)", "script",
        "satisfacao_revendedor_vd.py", ONEDRIVE, "medallia",
    ),
}

ORDEM = list(CATALOGO)

# Downloads da Extranet que alimentam o script.py (IAF de loja).
# Treinamentos saíram do IAF de loja (o script.py não os usa desde 20/10/2026).
ETAPAS_LOJA = [
    "servicos_em_loja",
    "loja_digital",
    "id_cliente",
    "acao_de_fluxo",
    "programa_fidelidade",
    "canal_loja",
]

# Fluxos diarios completos (terminam no Hubbia): sempre com dados de hoje,
# sem variaveis de periodo, e param na primeira etapa que falhar para nunca
# enviar dado incompleto. (nome, script, pasta, variaveis extras)
FLUXOS = {
    "loja": [
        (
            "Baixar indicadores de loja (Extranet)",
            "teste_playwright.py",
            PROJETO,
            {"ETAPAS": ",".join(ETAPAS_LOJA)},
        ),
        ("Coletar NPS (Medallia)", "nps2.py", ONEDRIVE, {}),
        ("Consolidar IAF (script.py)", "script.py", ONEDRIVE, {}),
        ("Enviar ao Hubbia", "upload_hubbia.py", ONEDRIVE, {}),
    ],
    "vd": [
        (
            "Baixar, consolidar e enviar Venda Direta ao Hubbia",
            "atualizar_vd_hubbia.py",
            ONEDRIVE,
            {},
        ),
    ],
    # Dashboard de Operações: PEC do 1º de janeiro até ontem + PL do mês,
    # importados nos botões da tela de Operações do Hubbia, e os pedidos do
    # Felipe (Consultar pedidos do VD+ por data de captação, CPF e CNPJ) no
    # cartão "Pedidos (ConsultaPedidos)". As datas e as pastas da execução são
    # montadas em montar_jobs_fluxo.
    "operacoes": [
        ("Baixar PEC (1º de janeiro até ontem)", "automacao_pec_envio_er.py", ONEDRIVE, {}),
        ("Baixar Plataforma Logística (mês atual)", "automacao_plataforma_logistica.py", ONEDRIVE, {}),
        ("Importar no Dashboard de Operações", "upload_operacoes_hubbia.py", ONEDRIVE, {}),
        ("Baixar meus pedidos: captação CPF e CNPJ (VD+)", "vdmais_relatorios.py", ONEDRIVE,
         {"VDMAIS_RELATORIO": "pedidos", "VDMAIS_PEDIDOS": "captacao_cpf,captacao_cnpj"}),
        ("Enviar pedidos ao Dashboard de Operações (Importar Pedidos)", "upload_pedidos_operacoes_hubbia.py", ONEDRIVE, {}),
    ],
    # Financeiro Loja: Gerencial de Vendas do Retaguarda (dia 1º até ontem,
    # por consultor, 3 recortes de canal) -> Comercial > Importação.
    "financeiro": [
        ("Baixar Gerencial de Vendas (Retaguarda)", "financeiro_loja_retaguarda.py", ONEDRIVE, {}),
        ("Importar no Comercial (Hubbia)", "financeiro_loja_hubbia.py", ONEDRIVE, {}),
    ],
    # Crédito da Beleza: dia 21 do mês passado até ontem. Gerencial sem
    # quebra e sem canal + Cupons de Venda -> Campanhas > Crédito da Beleza.
    "credito_beleza": [
        ("Baixar Gerencial de Vendas (Retaguarda)", "gerencial_credito_beleza.py", ONEDRIVE, {}),
        (
            "Baixar Cupons e importar no Crédito da Beleza",
            "auditoria_descontos.py",
            ONEDRIVE,
            {"AUDITORIA_DESTINO": "credito"},
        ),
    ],
    # Financeiro VD: Ranking de Vendas do VD+ (1º do mês até ontem, NF Emitida, por
    # Setor) -> Hubbia, Comercial > Importação, perfil VENDASPORSETOR.CSV (VD).
    "financeiro_vd": [
        ("Baixar Financeiro VD (VD+)", "vdmais_relatorios.py", ONEDRIVE, {"VDMAIS_RELATORIO": "ranking"}),
        ("Enviar ao Hubbia (VENDASPORSETOR.CSV)", "upload_financeiro_vd_hubbia.py", ONEDRIVE, {}),
    ],
    # Pedidos VD (Lucas): as 2 planilhas de situação/faturamento (CPF e CNPJ) do Consultar pedidos
    # do VD+ -> Hubbia, perfil PEDIDOS_GMS.CSV (VD), CPF e depois CNPJ. As 2 de captação (Felipe)
    # ficam no fluxo "operacoes".
    "pedidos_vd": [
        ("Baixar Pedidos por situação: CPF e CNPJ (VD+)", "vdmais_relatorios.py", ONEDRIVE,
         {"VDMAIS_RELATORIO": "pedidos", "VDMAIS_PEDIDOS": "situacao_cpf,situacao_cnpj"}),
        ("Enviar ao Hubbia (PEDIDOS_GMS: CPF e CNPJ)", "upload_pedidos_hubbia.py", ONEDRIVE, {}),
    ],
    # PEF (Gestão Integrada > Receita > Meta PEF Canal VD): mesma planilha "Resultado por PDV",
    # só muda o período. Realizado = 1º do mês até ontem; Meta = mês inteiro (só no começo do
    # mês). O realizado envia ao Hubbia (PERFORMANCE_PEF_PDV.CSV); a meta só baixa, até confirmar o formato do METAS_PEF.CSV.
    "pef_realizado": [
        ("Baixar PEF realizado (1º do mês até ontem)", "automacao_meta_pef.py", ONEDRIVE, {"PEF_MODO": "realizado"}),
        ("Enviar ao Hubbia (PERFORMANCE_PEF_PDV.CSV)", "upload_pef_hubbia.py", ONEDRIVE, {"PEF_MODO": "realizado"}),
    ],
    "pef_meta": [
        ("Baixar Meta PEF (mês inteiro)", "automacao_meta_pef.py", ONEDRIVE, {"PEF_MODO": "meta"}),
    ],
    # MAR (Abastecimento GB): Reposição semanal (todos os PDVs, últimos 3
    # ciclos) -> Hubbia Suprimentos > Atualização de PDVs.
    "mar": [
        ("Baixar Reposição semanal (MAR)", "mar_reposicao.py", ONEDRIVE, {}),
        ("Enviar à Atualização de PDVs (Hubbia)", "upload_mar_hubbia.py", ONEDRIVE, {}),
    ],
    # Periodo fixo: do dia 1 ate ontem (o proprio script calcula). Tambem
    # roda sozinho pelo Agendador do Windows as 08:35.
    "nps_digital": [
        (
            "Coletar NPS Loja Digital (Medallia) e gravar na HUBBia",
            "nps_loja_digital.py",
            ONEDRIVE,
            {},
        ),
    ],
}

PASTAS_ABRIR = {
    "dados_brutos": ONEDRIVE / "dados_brutos",
    "dados_brutos_periodos": ONEDRIVE / "dados_brutos periodos",
    "iaf_vd": ONEDRIVE / "iaf vd",
    "iaf_vd_ciclos": ONEDRIVE / "iaf vd ciclos",
    "iaf_vd_periodos": ONEDRIVE / "iaf vd periodos",
    "medallia_periodos": ONEDRIVE / "medallia periodos",
    "logs": PASTA_LOGS,
    "automacao": ONEDRIVE,
    "operacoes": ONEDRIVE / "operacoes",
    "financeiro": ONEDRIVE / "financeiro loja",
    "credito_beleza": ONEDRIVE / "credito beleza",
    "consolidacoes": ONEDRIVE / "consolidacoes",
    "mar": ONEDRIVE / "mar",
    "pef": ONEDRIVE / "pef",
    "mapeamentos": ONEDRIVE / "mapeamentos",
    "vdmais": ONEDRIVE / "vdmais",
    "auditoria": ONEDRIVE / "saida",
}

PADRAO_PERIODO_PASTA = re.compile(r"^\d{4}-\d{2}-\d{2}_a_\d{4}-\d{2}-\d{2}$")
FLUXO_DIARIO = "__diario__"

PADRAO_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")

TRAVA = threading.Lock()
estado: dict = {
    "rodando": False,
    "status": {},
    "linhas": [],
    "inicio": None,
    "fim": None,
    "resultado": None,
    "rotina": None,       # fluxos da "Rodar minha rotina", em ordem (None = execução avulsa)
    "iniciados": set(),   # chaves de etapa que chegaram a começar nesta execução
    "fechamento": None,   # mês (AAAA-MM) quando a execução é um item da aba Fechamento
}
processo_atual: subprocess.Popen | None = None
parar = threading.Event()


# ---------------------------------------------------------------- log

def registrar(texto: str) -> None:
    with TRAVA:
        estado["linhas"].append(texto)
        arquivo = estado.get("arquivo_log")
    if arquivo is not None:
        arquivo.write(texto + "\n")
        arquivo.flush()


# ----------------------------------------------------------- execucao

def ambiente_base(config: dict) -> dict:
    """Ambiente dos scripts: variaveis de periodo so as do config (as que
    estiverem esquecidas no Windows sao removidas)."""
    base = os.environ.copy()
    base["PYTHONIOENCODING"] = "utf-8"
    base["PYTHONUNBUFFERED"] = "1"

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
            base[variavel] = valor
        else:
            base.pop(variavel, None)
    # onde estão as pastas neste computador (teste_playwright.py e atualizar_vd_hubbia.py usam)
    base["AUTOMACAO_PASTA"] = str(ONEDRIVE)
    base["EXTRANET_PASTA"] = str(PROJETO)
    base.pop("HUB_SAIDA", None)
    base.pop("ETAPAS", None)
    base.pop("ETAPA_AUTOMACAO", None)
    base.pop("PULAR_EXTRANET", None)
    base.pop("RETOMAR_DE", None)
    base.pop("PULAR_EXTRACAO", None)
    base.pop("VDMAIS_PASTA", None)
    base.pop("VDMAIS_PEDIDOS", None)
    for variavel in ("MAR_PASTA", "FINANCEIRO_PASTA", "CREDITO_PASTA", "AUDITORIA_DESTINO", "OPERACOES_PASTA",
                     "AUDITORIA_REUSAR_CUPONS", "CREDITO_BLOCO"):
        base.pop(variavel, None)
    return base


def montar_jobs(ids: list[str], config: dict) -> list[dict]:
    base = ambiente_base(config)

    jobs: list[dict] = []

    etapas = [i for i in ids if CATALOGO[i][1] == "etapa"]
    if etapas:
        env = dict(base)
        env["ETAPAS"] = ",".join(etapas)
        jobs.append({
            "nome": "Indicadores da Extranet",
            "ids": etapas,
            "cmd": [sys.executable, "-u", "teste_playwright.py"],
            "cwd": PROJETO,
            "env": env,
            "agrupado": True,
        })

    tem_periodo = bool(
        config.get("periodo_inicio") and config.get("periodo_fim")
    )

    for i in ids:
        nome, tipo, script, pasta, sistema = CATALOGO[i]
        if tipo != "script":
            continue

        env = dict(base)

        # Medallia grava sempre no mesmo arquivo (nps.xlsx etc.): com
        # periodo definido, separa para nao sobrescrever o fluxo diario.
        if sistema == "medallia" and tem_periodo:
            ini = config["periodo_inicio"].replace("/", "-")
            fim = config["periodo_fim"].replace("/", "-")
            env["HUB_SAIDA"] = str(
                ONEDRIVE / "medallia periodos" / f"{ini}_a_{fim}"
            )

        jobs.append({
            "nome": nome,
            "ids": [i],
            "cmd": [sys.executable, "-u", script],
            "cwd": pasta,
            "env": env,
            "agrupado": False,
        })

    return jobs


def montar_jobs_fluxo(fluxo: str, opcoes: dict | None = None) -> list[dict]:
    opcoes = opcoes or {}
    base = ambiente_base({})
    jobs: list[dict] = []

    if fluxo == "operacoes":
        hoje = datetime.now()
        ontem = hoje - timedelta(days=1)
        pasta_execucao = ONEDRIVE / "operacoes" / f"{hoje:%Y-%m-%d}"
        base["HUB_SAIDA"] = str(pasta_execucao)
        base["OPERACOES_PASTA"] = str(pasta_execucao)

    if fluxo == "mar":
        base["MAR_PASTA"] = str(ONEDRIVE / "mar")
    if fluxo == "financeiro":
        base["FINANCEIRO_PASTA"] = str(
            ONEDRIVE / "financeiro loja" / f"{datetime.now():%Y-%m-%d}"
        )
    if fluxo == "credito_beleza":
        base["CREDITO_PASTA"] = str(
            ONEDRIVE / "credito beleza" / f"{datetime.now():%Y-%m-%d}"
        )
    if fluxo in ("financeiro_vd", "pedidos_vd", "operacoes"):
        base["VDMAIS_PASTA"] = str(
            ONEDRIVE / "vdmais" / f"{datetime.now():%Y-%m-%d}"
        )

    a_partir_de = int(opcoes.get("a_partir_de") or 1)
    for numero, (nome, script, pasta, extras) in enumerate(
        FLUXOS[fluxo], start=1
    ):
        if numero < a_partir_de:
            continue
        env = dict(base)
        env.update(extras)
        if fluxo == "credito_beleza" and script == "auditoria_descontos.py" and a_partir_de > 1:
            # retomando: reaproveita os Cupons do mesmo período já baixados
            env["AUDITORIA_REUSAR_CUPONS"] = "1"
        if fluxo == "operacoes" and script == "automacao_pec_envio_er.py":
            env["PERIODO_INICIO"] = f"01/01/{ontem:%Y}"
            env["PERIODO_FIM"] = f"{ontem:%d/%m/%Y}"
            nome = f"Baixar PEC ({env['PERIODO_INICIO']} a {env['PERIODO_FIM']})"
        if script == "atualizar_vd_hubbia.py" and opcoes.get("retomar_de"):
            env["RETOMAR_DE"] = opcoes["retomar_de"]
            nome = f"{nome} (retomando de: {RETOMADAS_VD[opcoes['retomar_de']]})"
        jobs.append({
            "nome": nome,
            "ids": [f"{fluxo}.{numero}"],
            "cmd": [sys.executable, "-u", script],
            "cwd": pasta,
            "env": env,
            "agrupado": False,
            "parar_no_erro": True,
        })

    return jobs


def rodar_job(job: dict) -> int:
    global processo_atual

    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP

    processo = subprocess.Popen(
        job["cmd"],
        cwd=str(job["cwd"]),
        env=job["env"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    processo_atual = processo

    falhas: set[str] = set()

    assert processo.stdout is not None
    for linha in processo.stdout:
        texto = linha.rstrip("\n")
        registrar(texto)
        achado = re.search(r"FALHA na etapa (\w+):", texto)
        if achado:
            falhas.add(achado.group(1))

    codigo = processo.wait()
    processo_atual = None

    job["falhas"] = falhas
    return codigo


def executar(ids: list[str], config: dict, jobs: list[dict] | None = None):
    if jobs is None:
        jobs = montar_jobs(ids, config)

    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    arquivo = open(
        PASTA_LOGS / f"{datetime.now():%Y-%m-%d_%H%M%S}.log",
        "w",
        encoding="utf-8",
    )

    with TRAVA:
        estado["arquivo_log"] = arquivo

    interrompido = False

    try:
        for indice, job in enumerate(jobs, start=1):
            if interrompido:
                registrar(f"Pulado: {job['nome']} (a etapa anterior falhou).")
                for i in job["ids"]:
                    estado["status"][i] = "cancelado"
                continue

            if parar.is_set():
                for i in job["ids"]:
                    estado["status"][i] = "cancelado"
                continue

            registrar("")
            registrar(f"===== [{indice}/{len(jobs)}] {job['nome']} =====")
            for i in job["ids"]:
                estado["status"][i] = "rodando"
                estado["iniciados"].add(i)

            try:
                if job.get("preparar"):
                    job["preparar"](registrar)
                codigo = rodar_job(job) if job.get("cmd") else 0
            except Exception as erro:
                registrar(f"Erro: {erro}")
                codigo = -1

            for i in job["ids"]:
                if parar.is_set():
                    estado["status"][i] = "cancelado"
                elif codigo == 0:
                    estado["status"][i] = "ok"
                elif job["agrupado"] and job.get("falhas"):
                    estado["status"][i] = (
                        "erro" if i in job["falhas"] else "ok"
                    )
                else:
                    estado["status"][i] = "erro"

            registrar(
                "-> concluído" if codigo == 0
                else f"-> terminou com erro (código {codigo})"
            )

            if codigo != 0 and job.get("parar_no_erro"):
                interrompido = True
    finally:
        with TRAVA:
            estado["rodando"] = False
            estado["fim"] = datetime.now().isoformat(timespec="seconds")
            valores = list(estado["status"].values())
            estado["resultado"] = (
                "cancelado" if parar.is_set()
                else "ok" if all(v in ("ok", "pulado") for v in valores)
                else "erro"
            )
            estado["arquivo_log"] = None
            registros = resultados_da_execucao(
                estado["status"], estado["linhas"], estado["inicio"], estado["fim"],
                estado["iniciados"],
            )
            mes_fechamento = estado["fechamento"]
            status_final = dict(estado["status"])
            iniciados_final = set(estado["iniciados"])
            fim_final = estado["fim"]
        if mes_fechamento:
            try:
                fechamento.registrar_resultados(mes_fechamento, status_final, iniciados_final, fim_final)
            except Exception as erro:  # noqa: BLE001
                registrar(f"Aviso: não consegui gravar o resultado do fechamento ({erro}).")
        try:
            for registro in registros:
                arquivo.write(MARCA_RESULTADO + json.dumps(registro, ensure_ascii=False) + "\n")
        finally:
            arquivo.close()


# ------------------------------------------------------- resultado do dia
# No fim de cada execução, uma linha por fluxo vai para o próprio log do dia:
#   ### PAINEL_RESULTADO {"fluxo": "financeiro", "etapas": {"1": "ok", "2": "erro"}, ...}
# O painel lê essas linhas dos logs de hoje para mostrar o último resultado de
# cada fluxo, mesmo depois de rodar outros ou recarregar a página.
MARCA_RESULTADO = "### PAINEL_RESULTADO "

# Fases do atualizar_vd_hubbia.py (a VD é um script só): a última que começou
# antes da falha é de onde a retomada recomeça (mesma ordem de RETOMADAS_VD).
FASES_VD = (
    ("Puxando os dados de Venda Direta", 1),
    ("Puxando a Satisfacao", 2),
    ("Puxando Plataforma Logistica", 3),
    ("Puxando PEC", 4),
    ("Consolidando as planilhas", 5),
    ("Abrindo o Hubbia", 5),
)


def fase_vd(linhas: list[str]) -> int:
    fase = 1
    for linha in linhas:
        for texto, numero in FASES_VD:
            if texto in linha:
                fase = numero
    return fase


def resultados_da_execucao(status: dict, linhas: list[str], inicio, fim, iniciados=None) -> list[dict]:
    por_fluxo: dict[str, dict] = {}
    for chave, situacao in status.items():
        if chave == "acao.auditoria":
            fluxo, numero = "auditoria", "1"
        else:
            fluxo, _, numero = chave.rpartition(".")
            if fluxo not in FLUXOS or not numero.isdigit():
                continue
        por_fluxo.setdefault(fluxo, {})[numero] = situacao
    registros = []
    for fluxo, etapas in por_fluxo.items():
        if iniciados is not None:
            chaves = ["acao.auditoria"] if fluxo == "auditoria" else [f"{fluxo}.{n}" for n in etapas]
            if not any(c in iniciados for c in chaves):
                continue  # nem começou (a rotina parou antes): continua "não rodou"
        registro = {"fluxo": fluxo, "etapas": etapas, "inicio": inicio, "fim": fim}
        if fluxo == "vd":
            registro["fase"] = fase_vd(linhas)
        registros.append(registro)
    return registros


def resumir_resultado(registro: dict) -> dict:
    fluxo = registro["fluxo"]
    etapas = {int(n): s for n, s in registro["etapas"].items()}
    total = 1 if fluxo == "auditoria" else len(FLUXOS.get(fluxo, [])) or 1
    hora = (registro.get("fim") or registro.get("inicio") or "")[11:16]
    erros = sorted(n for n, s in etapas.items() if s == "erro")
    canceladas = sorted(n for n, s in etapas.items() if s in ("cancelado", "aguardando", "rodando"))
    if not erros and not canceladas and etapas.get(total) == "ok" and all(
        s in ("ok", "pulado") for s in etapas.values()
    ):
        return {"estado": "enviado", "hora": hora}
    situacao = "falhou" if erros else "interrompido"
    # tudo o que rodou deu certo, mas o fluxo ganhou etapas depois (ex.: Operações
    # com os pedidos): retoma da primeira etapa que ainda não rodou
    seguinte = max((n for n, s in etapas.items() if s in ("ok", "pulado")), default=0) + 1
    etapa = (erros or canceladas or [min(seguinte, total)])[0]
    if fluxo == "vd":
        etapa = int(registro.get("fase") or 1)
    return {"estado": situacao, "etapa": etapa, "hora": hora}


LOG_NPS_DIGITAL = ONEDRIVE / "log_nps_loja_digital.txt"


def nps_automatico() -> dict | None:
    """O NPS Loja Digital roda sozinho às 08:35 pelo Agendador, fora do painel.
    O log dele só tem a hora; cada rodada começa com 'NPS Loja Digital: <ini> a
    <fim>' e o fim é sempre ontem, o que identifica a rodada de hoje."""
    try:
        if datetime.fromtimestamp(LOG_NPS_DIGITAL.stat().st_mtime).date() != datetime.now().date():
            return None
        linhas = LOG_NPS_DIGITAL.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    ontem = f"{datetime.now() - timedelta(days=1):%Y-%m-%d}"
    resultado = None
    dentro = False
    for linha in linhas:
        hora = linha[:5]
        cabeca = re.search(r"NPS Loja Digital: \d{4}-\d{2}-\d{2} a (\d{4}-\d{2}-\d{2})", linha)
        if cabeca:
            dentro = cabeca.group(1) == ontem
            if dentro:
                resultado = {"estado": "rodando", "hora": hora}
            continue
        if not dentro:
            continue
        if "Gravado em" in linha or "nada gravado" in linha:
            resultado = {"estado": "enviado", "hora": hora}
        elif "Falhou:" in linha:
            resultado = {"estado": "falhou", "etapa": 1, "hora": hora}
    if resultado and resultado["estado"] == "rodando":
        resultado = {"estado": "interrompido", "etapa": 1, "hora": resultado["hora"]}
    if resultado:
        resultado["automatico"] = True
    return resultado


_cache_hoje: dict = {"chave": None, "valor": {}}


def resultados_de_hoje() -> dict:
    """Último resultado de cada fluxo hoje, lido das marcas nos logs do dia."""
    hoje = f"{datetime.now():%Y-%m-%d}"
    arquivos = sorted(PASTA_LOGS.glob(f"{hoje}_*.log")) if PASTA_LOGS.exists() else []
    chave = (hoje, tuple((a.name, a.stat().st_mtime) for a in arquivos))
    if _cache_hoje["chave"] == chave:
        return _cache_hoje["valor"]
    resultado: dict[str, dict] = {}
    for arquivo in arquivos:
        try:
            texto = arquivo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for linha in texto.splitlines():
            if not linha.startswith(MARCA_RESULTADO):
                continue
            try:
                registro = json.loads(linha[len(MARCA_RESULTADO):])
                resultado[registro["fluxo"]] = {**resumir_resultado(registro), "log": arquivo.name}
            except (ValueError, KeyError, TypeError):
                continue
    _cache_hoje.update(chave=chave, valor=resultado)
    return resultado


def validar(ids: list, config: dict) -> str | None:
    if not ids:
        return "Marque pelo menos uma automação."
    if any(i not in CATALOGO for i in ids):
        return "Automação desconhecida."
    for campo in ("periodo_inicio", "periodo_fim"):
        valor = str(config.get(campo) or "").strip()
        if valor and not PADRAO_DATA.match(valor):
            return f"{campo} deve estar no formato dd/mm/aaaa."
    return None


def iniciar(ids: list[str], config: dict) -> str | None:
    erro = validar(ids, config)
    if erro:
        return erro

    ids = [i for i in ORDEM if i in ids]
    return comecar(montar_jobs(ids, config))


def listar_pastas() -> dict:
    def subpastas(pasta: Path, aceita) -> list[str]:
        if not pasta.is_dir():
            return []
        return sorted(
            (d.name for d in pasta.iterdir() if d.is_dir() and aceita(d.name)),
            reverse=True,
        )

    periodos = ONEDRIVE / "dados_brutos periodos"
    return {
        "vd": subpastas(ONEDRIVE / "iaf vd ciclos", lambda n: True),
        "loja": subpastas(periodos, lambda n: bool(PADRAO_PERIODO_PASTA.match(n))),
        "fluxo": subpastas(periodos, lambda n: n.startswith("acao_de_fluxo_")),
    }


def job_acao(chave: str, nome: str, args: list[str], env_extra=None, preparar=None) -> dict:
    env = ambiente_base({})
    env.update(env_extra or {})
    job = {
        "nome": nome,
        "ids": [f"acao.{chave}"],
        "cmd": [sys.executable, "-u", *args],
        "cwd": ONEDRIVE,
        "env": env,
        "agrupado": False,
    }
    if preparar is not None:
        job["preparar"] = preparar
    return job


def iniciar_acao(dados: dict) -> str | None:
    acao = str(dados.get("acao") or "")
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")

    if acao == "auditoria_login":
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            [sys.executable, "auditoria_descontos.py", "--login"],
            cwd=str(ONEDRIVE),
            env=ambiente_base({}),
            creationflags=flags,
        )
        return None

    if acao == "mar_login":
        # janela de console própria: o script espera o ENTER depois do login
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            [sys.executable, "mar_reposicao.py", "--login"],
            cwd=str(ONEDRIVE),
            env=ambiente_base({}),
            creationflags=flags,
        )
        return None

    if acao == "credito_anterior":
        # Repõe o bloco fechado (21 a 20) antes do atual. Fica fora do resultado
        # do dia (chave de ação, não de fluxo): o bloco atual continua pendente.
        env = {
            "CREDITO_BLOCO": "anterior",
            "CREDITO_PASTA": str(ONEDRIVE / "credito beleza" / f"{datetime.now():%Y-%m-%d}_bloco_anterior"),
        }
        baixar = job_acao("credito_anterior", "Crédito da Beleza, bloco anterior: Gerencial de Vendas",
                          ["gerencial_credito_beleza.py"], env)
        importar = job_acao("credito_anterior", "Crédito da Beleza, bloco anterior: Cupons e importação",
                            ["auditoria_descontos.py", "--destino", "credito"], env)
        baixar["parar_no_erro"] = importar["parar_no_erro"] = True
        return comecar([baixar, importar])

    if acao == "mar":
        return comecar([job_acao("mar", "Reposição semanal do MAR (últimos 3 ciclos)", ["mar_reposicao.py"])])

    if acao == "vdmais_preparar":
        # Chrome comum (sem automação) no perfil do VD+, numa janela de
        # console com as instruções; o Google recusa login automatizado.
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            [sys.executable, "vdmais.py", "--preparar"],
            cwd=str(ONEDRIVE),
            env=ambiente_base({}),
            creationflags=flags,
        )
        return None

    if acao == "vdmais_mapear":
        # Gravador: abre o Chrome do VD+ com a barra Gravar/Parar, numa janela
        # de console própria (o painel não fica preso à gravação).
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            [sys.executable, "mapear_vdmais.py"],
            cwd=str(ONEDRIVE),
            env=ambiente_base({}),
            creationflags=flags,
        )
        return None

    if acao == "vdmais_ranking":
        pasta = ONEDRIVE / "vdmais" / f"{datetime.now():%Y-%m-%d}"
        return comecar([job_acao(
            "vdmais_ranking", "Financeiro VD (Ranking de Vendas)",
            ["vdmais_relatorios.py", "ranking"], {"VDMAIS_PASTA": str(pasta)},
        )])

    if acao == "vdmais_pedidos":
        pasta = ONEDRIVE / "vdmais" / f"{datetime.now():%Y-%m-%d}"
        return comecar([job_acao(
            "vdmais_pedidos", "Pedidos VD (4 planilhas, só baixar)",
            ["vdmais_relatorios.py", "pedidos"], {"VDMAIS_PASTA": str(pasta)},
        )])

    if acao == "vdmais_testar":
        return comecar([job_acao("vdmais_testar", "Testar acesso ao VD+", ["vdmais.py"])])

    if acao == "auditoria":
        inicio = str(dados.get("inicio") or "").strip()
        fim = str(dados.get("fim") or "").strip()
        if bool(inicio) != bool(fim):
            return "Preencha as duas datas da auditoria ou deixe as duas em branco."
        args = ["auditoria_descontos.py"]
        for valor, flag in ((inicio, "--inicio"), (fim, "--fim")):
            if valor:
                if not PADRAO_DATA.match(valor):
                    return "As datas da auditoria devem estar no formato dd/mm/aaaa."
                args += [flag, valor]
        if dados.get("historico"):
            args.append("--historico")
        return comecar([job_acao("auditoria", "Auditoria de Descontos → HUBbia", args)])

    pastas = listar_pastas()

    if acao == "consolidar_vd":
        nome = str(dados.get("pasta") or "")
        if nome not in pastas["vd"]:
            return "Escolha uma pasta de ciclos da Venda Direta."
        origem = ONEDRIVE / "iaf vd ciclos" / nome
        destino = ONEDRIVE / "consolidacoes" / f"vd_{nome}_{carimbo}"
        saida = destino / f"Consolidado_{nome}.xlsx"
        return comecar([job_acao(
            "consolidar_vd",
            f"Consolidar Venda Direta ({nome})",
            ["consolidar_pasta.py", str(destino), str(saida)],
            preparar=lambda log: consolidacao.montar_pasta_vd(origem, destino, log),
        )])

    if acao == "consolidar_loja":
        periodo = str(dados.get("periodo") or "")
        fluxo = str(dados.get("fluxo") or "")
        if periodo not in pastas["loja"]:
            return "Escolha o período da loja a consolidar."
        if fluxo == FLUXO_DIARIO:
            pasta_fluxo = ONEDRIVE / "dados_brutos"
        elif fluxo in pastas["fluxo"]:
            pasta_fluxo = ONEDRIVE / "dados_brutos periodos" / fluxo
        else:
            return "Escolha de onde vem a Ação de Fluxo."
        destino = ONEDRIVE / "consolidacoes" / f"loja_{periodo}_{carimbo}"
        return comecar([job_acao(
            "consolidar_loja",
            f"Consolidar IAF Loja ({periodo})",
            ["script.py", str(destino)],
            preparar=lambda log: consolidacao.montar_pasta_loja(
                ONEDRIVE, periodo, pasta_fluxo, destino, log
            ),
        )])

    return "Ação desconhecida."


# Etapas de onde o fluxo VD pode retomar. O próprio pipeline confere se o
# que é reaproveitado foi baixado hoje e está completo.
RETOMADAS_VD = {
    "satisfacao": "Satisfação",
    "pl": "Plataforma Logística",
    "pec": "PEC",
    "consolidar": "Consolidação",
}


def iniciar_fluxo(fluxo: str, opcoes: dict | None = None) -> str | None:
    if fluxo not in FLUXOS:
        return "Fluxo desconhecido."
    opcoes = dict(opcoes or {})
    if fluxo == "vd":
        retomar = str(opcoes.get("retomar_de") or "")
        if retomar and retomar not in RETOMADAS_VD:
            return "Etapa de retomada desconhecida."
        opcoes["retomar_de"] = retomar
    total = len(FLUXOS[fluxo])
    try:
        a_partir_de = int(opcoes.get("a_partir_de") or 1)
    except (TypeError, ValueError):
        return "Etapa inicial inválida."
    if not 1 <= a_partir_de <= total:
        return "Etapa inicial inválida."
    opcoes["a_partir_de"] = a_partir_de
    pulados = [f"{fluxo}.{n}" for n in range(1, a_partir_de)]
    return comecar(montar_jobs_fluxo(fluxo, opcoes), pulados)


ROTINA_FLUXOS = {"credito_beleza", "auditoria", "operacoes", "mar", "vd"}


def iniciar_rotina(dados: dict) -> str | None:
    """Encadeia os fluxos escolhidos na prévia da rotina, em ordem, numa execução
    só. Para no primeiro que falhar (todo job tem parar_no_erro)."""
    itens = dados.get("itens") or []
    if not isinstance(itens, list) or not itens:
        return "Marque pelo menos um fluxo para a rotina."
    jobs: list[dict] = []
    pulados: list[str] = []
    ordem: list[str] = []
    for item in itens:
        fluxo = str((item or {}).get("fluxo") or "")
        if fluxo not in ROTINA_FLUXOS or fluxo in ordem:
            return "Fluxo da rotina inválido ou repetido."
        ordem.append(fluxo)
        if fluxo == "auditoria":
            job = job_acao("auditoria", "Auditoria de Descontos → HUBbia", ["auditoria_descontos.py"])
            job["parar_no_erro"] = True
            jobs.append(job)
            continue
        opcoes: dict = {}
        if fluxo == "vd":
            retomar = str(item.get("retomar_de") or "")
            if retomar and retomar not in RETOMADAS_VD:
                return "Etapa de retomada da Venda Direta inválida."
            opcoes["retomar_de"] = retomar
        try:
            a_partir_de = int(item.get("a_partir_de") or 1)
        except (TypeError, ValueError):
            return "Etapa inicial inválida."
        if not 1 <= a_partir_de <= len(FLUXOS[fluxo]):
            return "Etapa inicial inválida."
        opcoes["a_partir_de"] = a_partir_de
        pulados += [f"{fluxo}.{n}" for n in range(1, a_partir_de)]
        jobs += montar_jobs_fluxo(fluxo, opcoes)
    return comecar(jobs, pulados, rotina=ordem)


def comecar(jobs: list[dict], pulados: list[str] | None = None, rotina: list[str] | None = None,
            mes_fechamento: str | None = None) -> str | None:
    chaves = [i for job in jobs for i in job["ids"]]

    with TRAVA:
        if estado["rodando"]:
            return "Já existe uma execução em andamento."
        parar.clear()
        estado.update({
            "rodando": True,
            "status": {
                **{i: "pulado" for i in (pulados or [])},
                **{i: "aguardando" for i in chaves},
            },
            "linhas": [],
            "inicio": datetime.now().isoformat(timespec="seconds"),
            "fim": None,
            "resultado": None,
            "rotina": rotina,
            "iniciados": set(),
            "fechamento": mes_fechamento,
        })

    threading.Thread(
        target=executar, args=(chaves, {}, jobs), daemon=True
    ).start()
    return None


def iniciar_fechamento(dados: dict) -> str | None:
    mes = str(dados.get("mes") or "")
    try:
        a_partir_de = int(dados.get("a_partir_de") or 1)
    except (TypeError, ValueError):
        return "Etapa inicial inválida."
    montado = fechamento.montar_jobs(str(dados.get("item") or ""), mes, a_partir_de)
    if isinstance(montado, str):
        return montado
    jobs, pulados = montado
    return comecar(jobs, pulados, mes_fechamento=mes)


def parar_execucao() -> None:
    parar.set()
    processo = processo_atual
    if processo is not None and processo.poll() is None:
        registrar("Parando...")
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(processo.pid), "/T", "/F"],
                capture_output=True,
            )
        else:
            processo.terminate()


# ----------------------------------------------------------- ambiente

def ler_env(caminho: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.strip().startswith("#"):
                chave, _, valor = linha.partition("=")
                valores[chave.strip()] = valor.strip()
    return valores


def checar_ambiente() -> dict:
    # logins: .env local de quem roda (carregado no início) e, para a Extranet,
    # também o .env da pasta do projeto (o teste_playwright.py lê os dois)
    env_proj = ler_env(PROJETO / ".env")

    def tem(*chaves: str) -> bool:
        return all(os.environ.get(c) or env_proj.get(c) for c in chaves)

    return {
        "env_local": str(caminhos.ENV_LOCAL),
        "env_local_existe": caminhos.ENV_LOCAL.is_file(),
        "env_compartilhado": (ONEDRIVE / ".env").is_file(),
        "usuario": QUEM,
        "extranet": tem("EXTRANET_USUARIO", "EXTRANET_SENHA"),
        "hubbia": tem("HUBBIA_EMAIL", "HUBBIA_SENHA"),
        "retaguarda": tem("RETAGUARDA_USUARIO", "RETAGUARDA_SENHA"),
        "medallia": tem("BOTI_USUARIO", "BOTI_SENHA"),
        "scripts_ok": all(
            (
                (PROJETO / "teste_playwright.py").exists()
                if script is None
                else (pasta / script).exists()
            )
            for _, _, script, pasta, _ in CATALOGO.values()
        ),
        "fluxos_ok": all(
            (pasta / script).exists()
            for passos in FLUXOS.values()
            for _, script, pasta, _ in passos
        ),
        "pasta_onedrive": str(ONEDRIVE),
        "pasta_onedrive_existe": ONEDRIVE.is_dir(),
    }


# --------------------------------------------------------------- http

class Manipulador(BaseHTTPRequestHandler):
    def log_message(self, formato, *args):
        pass

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in (
            f"127.0.0.1:{PORTA}", f"localhost:{PORTA}",
        )

    def _json(self, dados, codigo=200):
        corpo = json.dumps(dados).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _autorizado(self) -> bool:
        return (
            self._host_ok()
            and self.headers.get("X-Token", "") == TOKEN
        )

    def do_GET(self):
        url = urlparse(self.path)

        if not self._host_ok():
            self.send_error(403)
            return

        if url.path == "/":
            html = (PAINEL / "painel.html").read_text(encoding="utf-8")
            html = html.replace("__TOKEN__", TOKEN)
            corpo = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return

        if not self._autorizado():
            self._json({"erro": "não autorizado"}, 403)
            return

        if url.path == "/api/estado":
            desde = int(parse_qs(url.query).get("desde", ["0"])[0])
            with TRAVA:
                resposta = {
                    "rodando": estado["rodando"],
                    "status": dict(estado["status"]),
                    "linhas": estado["linhas"][desde:],
                    "proximo": len(estado["linhas"]),
                    "inicio": estado["inicio"],
                    "fim": estado["fim"],
                    "resultado": estado["resultado"],
                    "rotina": estado["rotina"],
                }
            self._json(resposta)
        elif url.path == "/api/hoje":
            fluxos = dict(resultados_de_hoje())
            nps = nps_automatico()
            if nps:  # o log do próprio script vale para a rodada agendada e para a do painel
                fluxos["nps_digital"] = nps
            self._json({"fluxos": fluxos})
        elif url.path == "/api/fechamento":
            mes = parse_qs(url.query).get("mes", [""])[0] or fechamento.mes_padrao()
            if not fechamento.PADRAO_MES.match(mes):
                self._json({"erro": "Mês inválido."}, 400)
                return
            self._json(fechamento.resposta(mes))
        elif url.path == "/api/pastas":
            self._json(listar_pastas())
        elif url.path == "/api/ambiente":
            self._json(checar_ambiente())
        else:
            self.send_error(404)

    def do_POST(self):
        if not self._autorizado():
            self._json({"erro": "não autorizado"}, 403)
            return

        tamanho = int(self.headers.get("Content-Length", "0"))
        try:
            dados = json.loads(self.rfile.read(tamanho) or b"{}")
        except json.JSONDecodeError:
            self._json({"erro": "JSON inválido"}, 400)
            return

        if self.path == "/api/executar":
            erro = iniciar(
                list(dados.get("ids") or []),
                dict(dados.get("config") or {}),
            )
            if erro:
                self._json({"erro": erro}, 409 if "andamento" in erro else 400)
            else:
                self._json({"ok": True})
        elif self.path == "/api/rotina":
            erro = iniciar_rotina(dados)
            if erro:
                self._json({"erro": erro}, 409 if "andamento" in erro else 400)
            else:
                self._json({"ok": True})
        elif self.path == "/api/fluxo":
            erro = iniciar_fluxo(str(dados.get("fluxo") or ""), dados)
            if erro:
                self._json({"erro": erro}, 409 if "andamento" in erro else 400)
            else:
                self._json({"ok": True})
        elif self.path == "/api/acao":
            erro = iniciar_acao(dados)
            if erro:
                self._json({"erro": erro}, 409 if "andamento" in erro else 400)
            else:
                self._json({"ok": True})
        elif self.path == "/api/fechamento/rodar":
            erro = iniciar_fechamento(dados)
            if erro:
                self._json({"erro": erro}, 409 if "andamento" in erro else 400)
            else:
                self._json({"ok": True})
        elif self.path in ("/api/fechamento/marcar", "/api/fechamento/ciclos"):
            mes = str(dados.get("mes") or "")
            erro = (
                fechamento.marcar(mes, str(dados.get("item") or ""), bool(dados.get("feito")))
                if self.path.endswith("marcar")
                else fechamento.salvar_ciclos(mes, dados.get("ciclos"), dados.get("qtd", 2))
            )
            if erro:
                self._json({"erro": erro}, 400)
            else:
                self._json(fechamento.resposta(mes))
        elif self.path == "/api/fechamento/abrir":
            mes = str(dados.get("mes") or "")
            if not fechamento.PADRAO_MES.match(mes):
                self._json({"erro": "Mês inválido."}, 400)
                return
            pasta = fechamento.pasta_mes(mes)
            pasta.mkdir(parents=True, exist_ok=True)
            os.startfile(str(pasta))  # type: ignore[attr-defined]
            self._json({"ok": True})
        elif self.path == "/api/parar":
            parar_execucao()
            self._json({"ok": True})
        elif self.path == "/api/abrir":
            pasta = PASTAS_ABRIR.get(str(dados.get("alvo")))
            if pasta is None:
                self._json({"erro": "pasta desconhecida"}, 400)
                return
            pasta.mkdir(parents=True, exist_ok=True)
            os.startfile(str(pasta))  # type: ignore[attr-defined]
            self._json({"ok": True})
        else:
            self.send_error(404)


fechamento.ctx = sys.modules[__name__]


def main() -> int:
    url = f"http://127.0.0.1:{PORTA}/"

    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Manipulador)
    except OSError:
        print(f"O painel já está aberto em {url}")
        webbrowser.open(url)
        return 0

    print("=" * 60)
    print(" PAINEL DE AUTOMAÇÕES")
    print(f" Endereço: {url}")
    print(" Deixe esta janela aberta enquanto usa o painel.")
    print(" Para encerrar, feche esta janela.")
    print("=" * 60)

    # PAINEL_SEM_NAVEGADOR=1 sobe so o servidor (para testes).
    if not os.environ.get("PAINEL_SEM_NAVEGADOR"):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
