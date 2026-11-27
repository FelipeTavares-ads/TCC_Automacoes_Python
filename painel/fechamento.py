"""Fechamento de Variável: o que precisa estar no Hubbia para fechar um mês.

Baseado no guia "Fontes de dados do Fechamento de Variável". Cada item é:
  - "envia":  baixa com o período do mês e envia ao Comercial (fluxos de sempre);
  - "baixa":  só baixa e organiza em  fechamento/AAAA-MM/<grupo>/<item>  para
              soltar à mão no Hubbia (as planilhas da VD em Unidades e ciclos);
  - "manual": feito fora do painel; fica como checklist marcado por mês.

O estado de cada mês (ciclos, resultado das automações e o que foi marcado)
fica em painel/fechamento.json. O painel_local injeta o próprio módulo em
`ctx` (ambiente_base, FLUXOS, ONEDRIVE...) para não haver import circular.
"""

from __future__ import annotations

import calendar
import json
import re
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import consolidacao

ctx = None  # módulo painel_local, preenchido por ele ao subir
ARQUIVO = Path(__file__).resolve().parent / "fechamento.json"
PADRAO_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_trava = threading.Lock()

GRUPOS = [
    {"id": "loja", "titulo": "Loja", "nota": "A variável sai do Comercial (Dashboard Loja › Por Consultor)."},
    {"id": "digital", "titulo": "Loja Digital", "nota": "A venda digital desconta a meta da loja física desde nov/2026."},
    {"id": "vd_unidades", "titulo": "Venda Direta · Unidades e ciclos",
     "nota": "Só baixa e organiza na pasta do mês: solte cada arquivo em Fechamento › Venda Direta › Unidades e ciclos."},
    {"id": "vd_comercial", "titulo": "Venda Direta · Comercial", "nota": "Planilhas do Comercial que o Fechamento reaproveita."},
    {"id": "financeiro", "titulo": "Conferência e publicação", "nota": "Feito no Fechamento de Variável depois do dia 10."},
]

# id, grupo, tipo, nome, onde (no Hubbia), prazo, descrição, etapas (automáticos)
ITENS = [
    # ---------------------------------------------------------------- Loja
    {"id": "loja_vendas", "grupo": "loja", "tipo": "envia",
     "nome": "vendas.csv e cliqueretire.csv", "onde": "Comercial › Importação", "prazo": "dia 5",
     "desc": "Gerencial de Vendas do mês inteiro (por consultor): vendas e o Clique e Retire (parcerias), que soma só no faturamento da loja.",
     "etapas": ["Baixar Gerencial de Vendas do mês (Retaguarda)", "Importar no Comercial (Hubbia)"]},
    {"id": "loja_metas", "grupo": "loja", "tipo": "manual",
     "nome": "metas.csv (Loja)", "onde": "Comercial › Importação › Metas", "prazo": "dia 5",
     "desc": "Meta da loja, depois dividida entre as consultoras."},
    {"id": "loja_iaf", "grupo": "loja", "tipo": "baixa",
     "nome": "Planilhas do IAF do mês", "onde": "IAF › Importar Dados", "prazo": "dia 5",
     "desc": "Super_, Totais_ e Consultor_Dashboard_Final.xlsx do mês fechado (NPS, Skin, ID Cliente). Ficam na pasta do mês, em Loja/IAF/consolidado.",
     "etapas": ["Baixar indicadores de loja do mês (Extranet)", "Coletar NPS do mês (Medallia)", "Consolidar IAF do mês (script.py)"]},
    {"id": "loja_iaf_importar", "grupo": "loja", "tipo": "manual",
     "nome": "Planilhas do IAF importadas", "onde": "IAF › Importar Dados", "prazo": "dia 5",
     "desc": "O nome da consultora na Consultor_Dashboard_Final precisa bater com o da vendas.csv; se divergir, use \"Vincular indicador IAF\" no Por Consultor."},
    # -------------------------------------------------------- Loja Digital
    {"id": "ld_caixa", "grupo": "digital", "tipo": "manual",
     "nome": "Caixa da Loja Digital em dia (Ellen)", "onde": "Comercial › Loja Digital › Cupons e caixa", "prazo": "diariamente",
     "desc": "CSV do caixa da Ellen. Pedido com PDV errado desconta a meta da loja errada: corrigir na planilha dela."},
    {"id": "ld_performance", "grupo": "digital", "tipo": "manual",
     "nome": "LojaDigital_Performance_por_Pdv_Consultor.xlsx", "onde": "Comercial › Importação", "prazo": "dia 5",
     "desc": "Aba PDV: clientes atendidos, convertidos, conversão e TME da Loja Digital."},
    {"id": "ld_meta", "grupo": "digital", "tipo": "manual",
     "nome": "Meta da Consultora Digital digitada", "onde": "Comercial › Loja Digital", "prazo": "dia 5",
     "desc": "Meta da Ellen; o realizado dela é o total do canal em todas as lojas."},
    # ------------------------------------------------- VD: Unidades e ciclos
    {"id": "vd_ciclo1", "grupo": "vd_unidades", "tipo": "baixa", "ciclo": 0,
     "nome": "Monitoramento de Base · 1º ciclo", "onde": "Unidades e ciclos", "prazo": "dia 5",
     "desc": "Adições e atividades (Monitoramento por supervisor), Penetração de base e Categorias do ciclo, geral e por ER.",
     "etapas": ["Baixar Monitoramento de Base do ciclo (Extranet)", "Separar na pasta do fechamento"]},
    {"id": "vd_ciclo2", "grupo": "vd_unidades", "tipo": "baixa", "ciclo": 1, "so_dois_ciclos": True,
     "nome": "Monitoramento de Base · 2º ciclo", "onde": "Unidades e ciclos", "prazo": "dia 5",
     "desc": "Mesmas planilhas do 1º ciclo, para o 2º ciclo do mês. Não se aplica em mês de um ciclo só.",
     "etapas": ["Baixar Monitoramento de Base do ciclo (Extranet)", "Separar na pasta do fechamento"]},
    {"id": "vd_consolidado", "grupo": "vd_unidades", "tipo": "baixa",
     "nome": "Consolidado do mês (vd.py)", "onde": "Unidades e ciclos", "prazo": "dia 5",
     "desc": "Consolidado_AAAA-MM-DD_a_AAAA-MM-DD.xlsx: Multimarcas, Make, Cabelos, Atividade e Base por ER e GMS, com o(s) ciclo(s) do mês. A HUBBia lê o mês pelo nome do arquivo.",
     "etapas": ["Baixar Monitoramento de Base do(s) ciclo(s) do mês (Extranet)", "Consolidar (consolidar_pasta.py)"]},
    {"id": "vd_pl", "grupo": "vd_unidades", "tipo": "baixa",
     "nome": "Plataforma Logística", "onde": "Unidades e ciclos", "prazo": "dia 5",
     "desc": "Do dia 21 do mês anterior ao dia 20 do mês: % de pedidos \"Usa bem\" por ER.",
     "etapas": ["Baixar Plataforma Logística (21 a 20)"]},
    {"id": "vd_pec", "grupo": "vd_unidades", "tipo": "baixa",
     "nome": "PEC (Omni)", "onde": "Unidades e ciclos", "prazo": "dia 5",
     "desc": "Mês fechado: % de pedidos dentro do prazo por ER.",
     "etapas": ["Baixar PEC do mês (Extranet)"]},
    {"id": "vd_satisfacao", "grupo": "vd_unidades", "tipo": "baixa",
     "nome": "Satisfação do revendedor", "onde": "Unidades e ciclos", "prazo": "dia 5",
     "desc": "Mês fechado: satisfação por ER (colunas ER e Valor).",
     "etapas": ["Coletar Satisfação do mês (Medallia)"]},
    {"id": "vd_unidades_soltar", "grupo": "vd_unidades", "tipo": "manual",
     "nome": "Soltas em Unidades e ciclos e conferido \"O que falta neste mês\"", "onde": "Fechamento › Venda Direta › Unidades e ciclos", "prazo": "dia 5",
     "desc": "A HUBBia reconhece cada arquivo pelo conteúdo, não pelo nome."},
    # ------------------------------------------------------ VD: Comercial
    {"id": "vd_vendasporsetor", "grupo": "vd_comercial", "tipo": "envia",
     "nome": "vendasporsetor.csv", "onde": "Comercial › Importação", "prazo": "dia 5",
     "desc": "Ranking de Vendas do VD+ do mês inteiro (NF Emitida, por Setor): GMS realizado por setor e por ER.",
     "etapas": ["Baixar Financeiro VD do mês (VD+)", "Enviar ao Hubbia (VENDASPORSETOR.CSV)"]},
    {"id": "vd_pedidos", "grupo": "vd_comercial", "tipo": "envia",
     "nome": "ConsultaPedidos.xlsx", "onde": "Comercial › Importação", "prazo": "dia 5",
     "desc": "Pedidos faturados do mês inteiro: redistribuição do HUB 23924 entre as ERs abastecidas.",
     "etapas": ["Baixar Pedidos do mês (VD+)", "Enviar ao Hubbia (PEDIDOS_GMS.CSV)"]},
    {"id": "vd_superplano", "grupo": "vd_comercial", "tipo": "manual",
     "nome": "detalhe_revendedor.csv dos ciclos do mês (SuperPlano)", "onde": "Comercial › Importação", "prazo": "dia 5",
     "desc": "Base e Atividade por ciclo e setor. O nome no SuperPlano precisa bater com o do cadastro."},
    {"id": "vd_metas", "grupo": "vd_comercial", "tipo": "manual",
     "nome": "metas.csv (VD)", "onde": "Comercial › Importação", "prazo": "dia 5",
     "desc": "Metas de faturamento, atividade e adições por setor."},
    {"id": "vd_mapeamento", "grupo": "vd_comercial", "tipo": "manual",
     "nome": "mapeamento_vd.csv", "onde": "Comercial › Importação", "prazo": "dia 5",
     "desc": "Setor → ER e supervisora (quem recebe pelo setor)."},
    {"id": "vd_metas_pef", "grupo": "vd_comercial", "tipo": "manual",
     "nome": "metas_pef.csv", "onde": "Comercial › Importação", "prazo": "dia 5",
     "desc": "Meta Eudora por ER."},
    {"id": "vd_eudora", "grupo": "vd_comercial", "tipo": "manual",
     "nome": "ConsultaRankingVendas.xlsx (Eudora)", "onde": "Comercial › Importação", "prazo": "dia 5",
     "desc": "Realizado Eudora por ER."},
    # --------------------------------------------- Conferência e publicação
    {"id": "gente", "grupo": "financeiro", "tipo": "manual",
     "nome": "Cadastro conferido e férias aprovadas", "onde": "Colaboradores e Férias", "prazo": "durante o mês",
     "desc": "Gente e Cultura: admissões, desligamentos, trocas de função (com data de vigência) e afastamentos. Férias pendentes não contam."},
    {"id": "faltas", "grupo": "financeiro", "tipo": "manual",
     "nome": "Faltas lançadas pelos gerentes de VD", "onde": "Fechamento › Faltas", "prazo": "dia 10",
     "desc": "Faltas lançadas só na planilha da Gente e Cultura não entram: precisam estar na aba Faltas."},
    {"id": "acuracidade", "grupo": "financeiro", "tipo": "manual",
     "nome": "Acuracidade de estoque por ER digitada", "onde": "Fechamento de Variável", "prazo": "depois do dia 10",
     "desc": "Sim ou não por ER, mais salário dos gerentes de VD e exceções por pessoa."},
    {"id": "pendencias", "grupo": "financeiro", "tipo": "manual",
     "nome": "Pendências resolvidas", "onde": "Fechamento de Variável", "prazo": "depois do dia 10",
     "desc": "Pessoa sem ER, supervisora sem setor, cargo sem regra."},
    {"id": "publicar", "grupo": "financeiro", "tipo": "manual",
     "nome": "Loja e VD publicadas e folha exportada", "onde": "Fechamento de Variável", "prazo": "depois do dia 10",
     "desc": "Enquanto não publica, a prévia recalcula toda vez que alguém abre a tela. Publicar congela o valor."},
]
POR_ID = {i["id"]: i for i in ITENS}


# ------------------------------------------------------------------ datas

def mes_padrao(hoje: date | None = None) -> str:
    """O mês a fechar é sempre o anterior."""
    hoje = hoje or date.today()
    anterior = hoje.replace(day=1) - timedelta(days=1)
    return f"{anterior:%Y-%m}"


def limites(mes: str) -> tuple[date, date]:
    ano, m = (int(x) for x in mes.split("-"))
    return date(ano, m, 1), date(ano, m, calendar.monthrange(ano, m)[1])


def periodo_pl(mes: str) -> tuple[date, date]:
    ini, _ = limites(mes)
    anterior = ini - timedelta(days=1)
    return anterior.replace(day=21), ini.replace(day=20)


def br(d: date) -> str:
    return f"{d:%d/%m/%Y}"


def pasta_mes(mes: str) -> Path:
    return ctx.ONEDRIVE / "fechamento" / mes


# ----------------------------------------------------------------- estado

def _ler() -> dict:
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _gravar(dados: dict) -> None:
    temporario = ARQUIVO.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    temporario.replace(ARQUIVO)


def _mes(dados: dict, mes: str) -> dict:
    return dados.setdefault(mes, {"ciclos": ["", ""], "qtd_ciclos": 2, "auto": {}, "feitos": {}})


def estado_do_mes(mes: str) -> dict:
    with _trava:
        registro = _ler().get(mes) or {}
    ini, fim = limites(mes)
    pl_ini, pl_fim = periodo_pl(mes)
    return {
        "mes": mes,
        "periodo": [br(ini), br(fim)],
        "periodo_pl": [br(pl_ini), br(pl_fim)],
        "ciclos": registro.get("ciclos") or ["", ""],
        # o mês conta os ciclos com mais dias nele: às vezes um, às vezes dois
        "qtd_ciclos": 1 if registro.get("qtd_ciclos") == 1 else 2,
        "auto": registro.get("auto") or {},
        "feitos": registro.get("feitos") or {},
        "pasta": str(pasta_mes(mes)),
    }


def resposta(mes: str) -> dict:
    return {"padrao": mes_padrao(), "grupos": GRUPOS, "itens": ITENS, **estado_do_mes(mes)}


def marcar(mes: str, item: str, feito: bool) -> str | None:
    if not PADRAO_MES.match(mes):
        return "Mês inválido."
    if POR_ID.get(item, {}).get("tipo") != "manual":
        return "Item manual desconhecido."
    with _trava:
        dados = _ler()
        feitos = _mes(dados, mes)["feitos"]
        if feito:
            feitos[item] = datetime.now().isoformat(timespec="minutes")
        else:
            feitos.pop(item, None)
        _gravar(dados)
    return None


def salvar_ciclos(mes: str, ciclos, qtd=2) -> str | None:
    if not PADRAO_MES.match(mes):
        return "Mês inválido."
    if not isinstance(ciclos, list) or len(ciclos) != 2:
        return "Informe os ciclos do mês."
    if qtd not in (1, 2):
        return "O mês tem 1 ou 2 ciclos."
    limpos = [str(c or "").strip() for c in ciclos]
    if any(c and not c.isdigit() for c in limpos):
        return "Os ciclos são números (ex.: 15 e 16)."
    with _trava:
        dados = _ler()
        registro = _mes(dados, mes)
        registro["ciclos"] = limpos
        registro["qtd_ciclos"] = qtd
        _gravar(dados)
    return None


def registrar_resultados(mes: str, status: dict, iniciados: set, fim: str | None) -> None:
    """Chamado no fim de cada execução do fechamento: guarda por item o último
    resultado (enviado/baixado, ou a etapa que falhou)."""
    por_item: dict[str, dict[int, str]] = {}
    for chave, situacao in status.items():
        partes = chave.split(".")
        if len(partes) == 3 and partes[0] == "fech" and partes[2].isdigit():
            por_item.setdefault(partes[1], {})[int(partes[2])] = situacao
    if not por_item:
        return
    with _trava:
        dados = _ler()
        auto = _mes(dados, mes)["auto"]
        for item, etapas in por_item.items():
            if item not in POR_ID or not any(f"fech.{item}.{n}" in iniciados for n in etapas):
                continue
            total = len(POR_ID[item]["etapas"])
            erros = sorted(n for n, s in etapas.items() if s == "erro")
            paradas = sorted(n for n, s in etapas.items() if s in ("cancelado", "aguardando", "rodando"))
            if not erros and not paradas and etapas.get(total) == "ok":
                auto[item] = {"estado": "ok", "quando": fim}
            else:
                auto[item] = {"estado": "falhou" if erros else "interrompido",
                              "etapa": (erros or paradas or [1])[0], "quando": fim}
        _gravar(dados)


# ------------------------------------------------------------------- jobs

def _job(item: str, n: int, nome: str, env: dict, cmd: list[str] | None = None,
         cwd: Path | None = None, preparar=None) -> dict:
    job = {
        "nome": nome,
        "ids": [f"fech.{item}.{n}"],
        "cmd": [sys.executable, "-u", *cmd] if cmd else None,
        "cwd": cwd or ctx.ONEDRIVE,
        "env": env,
        "agrupado": False,
        "parar_no_erro": True,
    }
    if preparar is not None:
        job["preparar"] = preparar
    return job


def _jobs_fluxo(item: str, fluxo: str, env: dict, rotulo_mes: str) -> list[dict]:
    """Reaproveita as etapas de um fluxo diário com o período do mês."""
    jobs = []
    for n, (nome, script, pasta, extras) in enumerate(ctx.FLUXOS[fluxo], start=1):
        e = dict(env)
        e.update(extras)
        jobs.append(_job(item, n, f"{POR_ID[item]['etapas'][n - 1]} · {rotulo_mes}", e, [script], pasta))
    return jobs


def _vd_ciclos(item: str, n: int, ini: str, fim: str, env_base: dict) -> dict:
    env = dict(env_base)
    env["ETAPAS"] = "venda_direta"
    env["CICLO_INICIO"], env["CICLO_FIM"] = ini, fim
    rotulo = f"ciclo {ini}" if ini == fim else f"ciclos {ini} a {fim}"
    return _job(item, n, f"Monitoramento de Base ({rotulo}) · Extranet", env, ["teste_playwright.py"], ctx.PROJETO)


def _pasta_ciclos(ini: str, fim: str) -> Path:
    nome = f"ciclo_{ini}" if ini == fim else f"ciclos_{ini}_a_{fim}"
    return ctx.ONEDRIVE / "iaf vd ciclos" / nome


def montar_jobs(item: str, mes: str, a_partir_de: int = 1) -> tuple[list[dict], list[str]] | str:
    if not PADRAO_MES.match(mes):
        return "Mês inválido."
    definicao = POR_ID.get(item)
    if not definicao or definicao["tipo"] == "manual":
        return "Item do fechamento desconhecido."
    total = len(definicao["etapas"])
    if not 1 <= a_partir_de <= total:
        return "Etapa inicial inválida."

    ini, fim = limites(mes)
    rotulo_mes = f"{ini:%m/%Y}"
    destino = pasta_mes(mes)
    periodo = {"periodo_inicio": br(ini), "periodo_fim": br(fim)}
    estado = estado_do_mes(mes)
    ciclos, qtd_ciclos = estado["ciclos"], estado["qtd_ciclos"]
    jobs: list[dict] = []

    if item == "loja_vendas":
        env = ctx.ambiente_base(periodo)
        env["FINANCEIRO_PASTA"] = str(destino / "Loja" / "vendas e cliqueretire")
        jobs = _jobs_fluxo(item, "financeiro", env, rotulo_mes)

    elif item == "loja_iaf":
        nome_periodo = f"{ini:%Y-%m-%d}_a_{fim:%Y-%m-%d}"
        pasta_iaf = destino / "Loja" / "IAF"
        env = ctx.ambiente_base({**periodo, "campanhas": "todas"})
        env["ETAPAS"] = ",".join(ctx.ETAPAS_LOJA)
        jobs.append(_job(item, 1, f"Indicadores de loja · {rotulo_mes} (Extranet)", env, ["teste_playwright.py"], ctx.PROJETO))
        env = ctx.ambiente_base(periodo)
        env["HUB_SAIDA"] = str(ctx.ONEDRIVE / "medallia periodos" / f"{ini:%d-%m-%Y}_a_{fim:%d-%m-%Y}")
        jobs.append(_job(item, 2, f"NPS por loja · {rotulo_mes} (Medallia)", env, ["nps2.py"]))
        jobs.append(_job(
            item, 3, f"Consolidar IAF · {rotulo_mes}", ctx.ambiente_base({}), ["script.py", str(pasta_iaf)],
            preparar=lambda log: consolidacao.montar_pasta_loja(
                ctx.ONEDRIVE, nome_periodo,
                ctx.ONEDRIVE / "dados_brutos periodos" / "acao_de_fluxo_todas", pasta_iaf, log,
            ),
        ))

    elif item in ("vd_ciclo1", "vd_ciclo2"):
        if definicao.get("so_dois_ciclos") and qtd_ciclos == 1:
            return "Este mês tem um ciclo só: não há 2º ciclo para baixar."
        ciclo = ciclos[definicao["ciclo"]]
        if not ciclo:
            return "Preencha o(s) ciclo(s) do mês antes de baixar a VD."
        alvo = destino / "Venda Direta - Unidades e ciclos" / f"Monitoramento ciclo {ciclo}"
        jobs.append(_vd_ciclos(item, 1, ciclo, ciclo, ctx.ambiente_base({})))
        jobs.append(_job(
            item, 2, f"Separar as planilhas do ciclo {ciclo} na pasta do fechamento", {},
            preparar=lambda log: consolidacao.montar_pasta_vd(_pasta_ciclos(ciclo, ciclo), alvo, log),
        ))

    elif item == "vd_consolidado":
        usados = ciclos[:qtd_ciclos]
        if not all(usados):
            return "Preencha o(s) ciclo(s) do mês antes de baixar a VD."
        c1, c2 = (usados[0], usados[0]) if qtd_ciclos == 1 else sorted(usados, key=int)
        nome = f"{ini:%Y-%m-%d}_a_{fim:%Y-%m-%d}"
        limpa = ctx.ONEDRIVE / "consolidacoes" / f"fechamento_vd_{nome}_{datetime.now():%Y%m%d_%H%M%S}"
        saida = destino / "Venda Direta - Unidades e ciclos" / f"Consolidado_{nome}.xlsx"
        jobs.append(_vd_ciclos(item, 1, c1, c2, ctx.ambiente_base({})))
        rotulo_ciclos = f"ciclo {c1}" if c1 == c2 else f"ciclos {c1} a {c2}"
        jobs.append(_job(
            item, 2, f"Consolidar a VD de {rotulo_mes} ({rotulo_ciclos})", ctx.ambiente_base({}),
            ["consolidar_pasta.py", str(limpa), str(saida)],
            preparar=lambda log: (saida.parent.mkdir(parents=True, exist_ok=True),
                                  consolidacao.montar_pasta_vd(_pasta_ciclos(c1, c2), limpa, log)),
        ))

    elif item == "vd_pl":
        pl_ini, pl_fim = periodo_pl(mes)
        env = ctx.ambiente_base({"periodo_inicio": br(pl_ini), "periodo_fim": br(pl_fim)})
        env["HUB_SAIDA"] = str(destino / "Venda Direta - Unidades e ciclos" / "Plataforma Logistica")
        jobs.append(_job(item, 1, f"Plataforma Logística ({br(pl_ini)} a {br(pl_fim)})", env, ["automacao_plataforma_logistica.py"]))

    elif item == "vd_pec":
        env = ctx.ambiente_base(periodo)
        env["HUB_SAIDA"] = str(destino / "Venda Direta - Unidades e ciclos" / "PEC")
        jobs.append(_job(item, 1, f"PEC · {rotulo_mes} (Extranet)", env, ["automacao_pec_envio_er.py"]))

    elif item == "vd_satisfacao":
        env = ctx.ambiente_base(periodo)
        env["HUB_SAIDA"] = str(destino / "Venda Direta - Unidades e ciclos" / "Satisfacao")
        jobs.append(_job(item, 1, f"Satisfação do revendedor · {rotulo_mes} (Medallia)", env, ["satisfacao_revendedor_vd.py"]))

    elif item in ("vd_vendasporsetor", "vd_pedidos"):
        env = ctx.ambiente_base(periodo)
        env["VDMAIS_PASTA"] = str(destino / "Venda Direta - Comercial")
        fluxo = "financeiro_vd" if item == "vd_vendasporsetor" else "pedidos_vd"
        jobs = _jobs_fluxo(item, fluxo, env, rotulo_mes)

    pulados = [f"fech.{item}.{n}" for n in range(1, a_partir_de)]
    return jobs[a_partir_de - 1:], pulados
