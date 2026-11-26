import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from dotenv import load_dotenv
from playwright.sync_api import (
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    expect,
    sync_playwright,
)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

URL_SITE = "https://extranet.grupoboticario.com.br/"

URL_SERVICOS_EM_LOJA = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/instore-services"
)

URL_LOJA_DIGITAL = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/digital-store"
)

URL_TREINAMENTOS_FORCA_VENDAS = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/trainings/selling-force"
)

URL_TREINAMENTOS_IAF_CICLO = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/trainings/iaf-cycles"
)

URL_ID_CLIENTE = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/client-id"
)

URL_ACAO_DE_FLUXO = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/flow-action"
)

URL_PROGRAMA_FIDELIDADE = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/fidelity"
)

URL_CANAL_LOJA = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/store-view/performance"
)

URL_MONITORAMENTO_BASE_VD = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/direct-sales-view/base-monitoring"
)

PORTA_DEBUG = 9222

PASTA_PROJETO = Path(__file__).resolve().parent
ARQUIVO_ENV = PASTA_PROJETO / ".env"
PASTA_PERFIL = PASTA_PROJETO / "perfil_chrome_direto"

load_dotenv(ARQUIVO_ENV)

USUARIO = (
    os.getenv("EXTRANET_USUARIO")
    or os.getenv("USUARIO")
    or os.getenv("LOGIN")
)

SENHA = (
    os.getenv("EXTRANET_SENHA")
    or os.getenv("SENHA")
    or os.getenv("PASSWORD")
)

# Usa o OneDrive corporativo do usuário logado (varia por máquina/usuário);
# cai no caminho antigo se a variável do Windows não existir.
PASTA_AUTOMACAO_ONEDRIVE = (
    Path(os.environ["OneDriveCommercial"])
    / "dashboards" / "Teste Python" / "automacao"
    if os.environ.get("OneDriveCommercial")
    else Path(
        r"C:\Users\Admin\OneDrive - Maria Selma Souza Alves & Cia Ltda\dashboards\Teste Python\automacao"
    )
)

# O hub define HUB_SAIDA para gravar tudo numa pasta local da execução.
if os.environ.get("HUB_SAIDA", "").strip():
    PASTA_AUTOMACAO_ONEDRIVE = Path(os.environ["HUB_SAIDA"].strip())

PASTA_DOWNLOADS = PASTA_AUTOMACAO_ONEDRIVE / "dados_brutos"

# Planilhas de Venda Direta (Monitoramento de Base) têm pasta própria.
PASTA_DOWNLOADS_VD = Path(
    os.environ.get("PASTA_IAF_VD")
    or PASTA_AUTOMACAO_ONEDRIVE / "iaf vd"
)

# ERs (unidades de negócio) usados no loop de Monitoramento de Base.
ERS_VENDA_DIRETA = [
    "13481",
    "13483",
    "14523",
    "18481",
    "19081",
    "23332",
]

RELATORIOS_MONITORAMENTO_BASE = [
    (
        "Penetração de base no período de ciclos",
        None,
        "PenetracaoBaseVendaDireta",
    ),
    (
        "Detalhamento por UN e categoria no período de ciclos",
        None,
        "DetalhamentoCategoriasUNVendaDireta",
    ),
]

# Fonte de Atividade e Alcance da Meta de Base. Só é baixado na versão
# geral (sem filtro de ER) — não entra no loop por ER.
RELATORIO_MONITORAMENTO_BASE_GERAL = [
    (
        "Monitoramento da base por PDV / Supervisor(a)",
        None,
        "MonitoramentoBasePDVSupervisorVendaDireta",
    ),
]

DATA_ATUAL = datetime.now().strftime("%d-%m-%Y")

# Use ETAPA_AUTOMACAO=canal_loja para executar somente essa etapa.
# Sem a variável, a automação completa continua sendo executada.
ETAPA_AUTOMACAO = os.getenv(
    "ETAPA_AUTOMACAO",
    "completa",
).strip().lower()

# Limites máximos: o Playwright continua assim que o elemento aparece.
# Eles foram reduzidos para evitar esperas longas quando um seletor mudar.
TIMEOUT_NORMAL = 45_000
TIMEOUT_TREINAMENTOS = 120_000
TIMEOUT_RELATORIO = 900_000

# Pausa entre cliques/preenchimentos. Dois segundos dão tempo para
# animações, avisos e componentes do painel estabilizarem sem deixar
# a automação tão lenta quanto a versão antiga de 7 segundos.
ESPERA_ANTES_ACAO = 2_000

# Tempo para o dashboard terminar de atualizar depois de abrir uma área,
# limpar filtros ou trocar abas. O site continua montando componentes mesmo
# depois que o elemento principal já aparece na tela.
ESPERA_DASHBOARD = 8_000

# Tempo de cada tentativa de clique antes de usar o fallback.
TIMEOUT_CLIQUE = 8_000


# ============================================================
# FUNÇÕES GERAIS
# ============================================================

def log(mensagem: str):
    horario = datetime.now().strftime("%H:%M:%S")
    print(f"[{horario}] {mensagem}")


def esperar_antes(
    page: Page,
    milissegundos: int = ESPERA_ANTES_ACAO,
):
    page.wait_for_timeout(milissegundos)


def validar_configuracoes():
    if not USUARIO:
        raise ValueError(
            "Adicione EXTRANET_USUARIO no arquivo .env"
        )

    if not SENHA:
        raise ValueError(
            "Adicione EXTRANET_SENHA no arquivo .env"
        )

    PASTA_DOWNLOADS.mkdir(
        parents=True,
        exist_ok=True,
    )

    PASTA_DOWNLOADS_VD.mkdir(
        parents=True,
        exist_ok=True,
    )


def localizar_chrome() -> str:
    caminhos = [
        shutil.which("chrome.exe"),
        shutil.which("chrome"),
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google/Chrome/Application/chrome.exe",
    ]

    for caminho in caminhos:
        if caminho and Path(caminho).exists():
            return str(caminho)

    raise FileNotFoundError(
        "Google Chrome não encontrado."
    )


def obter_websocket_chrome() -> str:
    endereco = (
        f"http://127.0.0.1:{PORTA_DEBUG}/json/version"
    )

    opener = build_opener(
        ProxyHandler({})
    )

    for tentativa in range(1, 31):
        try:
            with opener.open(
                endereco,
                timeout=2,
            ) as resposta:
                dados = json.loads(
                    resposta.read().decode("utf-8")
                )

            websocket = dados.get(
                "webSocketDebuggerUrl"
            )

            if websocket:
                log("Interface de depuração encontrada.")
                return websocket

        except Exception:
            log(
                f"Aguardando Chrome ({tentativa}/30)..."
            )
            time.sleep(1)

    raise TimeoutError(
        "O Chrome não disponibilizou a interface de depuração."
    )


def escolher_pagina(contexto) -> Page:
    limite = time.time() + 60

    while time.time() < limite:
        paginas = [
            pagina
            for pagina in contexto.pages
            if pagina.url not in ("", "about:blank")
        ]

        if paginas:
            return paginas[-1]

        time.sleep(1)

    raise TimeoutError(
        "A página da Extranet não apareceu."
    )


def esperar_carregamento_inicial(page: Page):
    log("Aguardando a Extranet carregar...")

    limite = time.time() + 120

    while time.time() < limite:
        try:
            if page.url not in ("", "about:blank"):
                page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=10_000,
                )

                log(f"Página aberta: {page.url}")
                return

        except PlaywrightTimeoutError:
            if "extranet.grupoboticario.com.br" in page.url:
                log(f"Página disponível: {page.url}")
                return

        time.sleep(2)

    raise TimeoutError(
        "A Extranet não terminou o carregamento inicial."
    )


def criar_destino(
    nome_original: str,
    pasta_destino: Path = PASTA_DOWNLOADS,
) -> Path:
    # Usa exatamente o nome sugerido pelo site e remove qualquer
    # parte de caminho que eventualmente venha no cabeçalho.
    nome_original = Path(nome_original).name

    if not nome_original:
        nome_original = f"download-{DATA_ATUAL}.xlsx"

    destino = pasta_destino / nome_original

    if not destino.exists():
        return destino

    horario = datetime.now().strftime("%H-%M-%S")
    caminho_original = Path(nome_original)

    destino = pasta_destino / (
        f"{caminho_original.stem}-{horario}"
        f"{caminho_original.suffix}"
    )

    contador = 2

    while destino.exists():
        destino = pasta_destino / (
            f"{caminho_original.stem}-{horario}-{contador}"
            f"{caminho_original.suffix}"
        )
        contador += 1

    return destino


def salvar_download(
    download,
    _nome_base: str,
    pasta_destino: Path = PASTA_DOWNLOADS,
) -> Path:
    falha = download.failure()

    if falha:
        raise RuntimeError(
            f"Falha no download: {falha}"
        )

    destino = criar_destino(
        download.suggested_filename,
        pasta_destino,
    )

    download.save_as(str(destino))

    if not destino.exists():
        raise RuntimeError(
            f"O arquivo não foi encontrado: {destino}"
        )

    if destino.stat().st_size == 0:
        raise RuntimeError(
            f"O arquivo baixado está vazio: {destino}"
        )

    log(f"Arquivo salvo: {destino}")

    return destino


def clicar_se_aparecer(
    page: Page,
    locator: Locator,
    timeout: int = 5_000,
) -> bool:
    try:
        locator.wait_for(
            state="visible",
            timeout=timeout,
        )

        esperar_antes(page)
        locator.click()

        return True

    except PlaywrightTimeoutError:
        return False


def fechar_aviso_notificacoes(
    page: Page,
    timeout: int = 3_000,
) -> bool:
    """Fecha o aviso que pode cobrir os botões do dashboard."""
    aviso = page.get_by_text(
        "Ative as notificações",
        exact=False,
    ).last

    try:
        aviso.wait_for(
            state="visible",
            timeout=timeout,
        )

    except PlaywrightTimeoutError:
        return False

    log("Aviso de notificações detectado. Fechando...")

    botao_agora_nao = page.get_by_role(
        "button",
        name="Agora não",
        exact=False,
    ).last

    try:
        botao_agora_nao.wait_for(
            state="visible",
            timeout=TIMEOUT_CLIQUE,
        )
        botao_agora_nao.click(timeout=TIMEOUT_CLIQUE)

    except PlaywrightTimeoutError:
        # O próprio aviso também pode interceptar o clique no botão.
        if botao_agora_nao.count() > 0:
            botao_agora_nao.evaluate(
                "elemento => elemento.click()"
            )
        else:
            page.keyboard.press("Escape")

    try:
        aviso.wait_for(
            state="hidden",
            timeout=TIMEOUT_CLIQUE,
        )

    except PlaywrightTimeoutError:
        page.keyboard.press("Escape")

    log("Aviso de notificações fechado.")
    return True


def clicar_com_fallback(
    page: Page,
    locator: Locator,
    descricao: str,
):
    """Clica normalmente e contorna avisos/cabeçalho sobrepostos."""
    locator.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    expect(locator).to_be_enabled(
        timeout=TIMEOUT_NORMAL,
    )

    fechar_aviso_notificacoes(
        page,
        timeout=2_000,
    )

    locator.evaluate(
        """
        elemento => elemento.scrollIntoView({
            block: 'center',
            inline: 'center'
        })
        """
    )

    try:
        locator.click(timeout=TIMEOUT_CLIQUE)
        return

    except PlaywrightTimeoutError:
        log(
            f"O clique em {descricao} foi bloqueado. "
            "Tentando novamente..."
        )

    page.keyboard.press("Escape")
    fechar_aviso_notificacoes(
        page,
        timeout=2_000,
    )

    locator.evaluate(
        """
        elemento => elemento.scrollIntoView({
            block: 'center',
            inline: 'center'
        })
        """
    )

    try:
        locator.click(timeout=TIMEOUT_CLIQUE)
        return

    except PlaywrightTimeoutError:
        log(
            f"Usando clique direto no elemento {descricao}."
        )

    # Último recurso: dispara o clique no próprio botão, sem depender
    # das coordenadas do mouse que estão cobertas pelo aviso/cabeçalho.
    locator.evaluate("elemento => elemento.click()")


def esperar_botao_exportar(page: Page) -> Locator:
    log("Aguardando o botão Exportar...")

    botao = page.get_by_test_id(
        "button-export"
    )

    botao.wait_for(
        state="visible",
        timeout=TIMEOUT_TREINAMENTOS,
    )

    expect(botao).to_be_enabled(
        timeout=TIMEOUT_TREINAMENTOS,
    )

    log("Botão Exportar disponível.")

    return botao


def limpar_filtros(page: Page):
    log("Aguardando Limpar filtros...")

    botao = page.get_by_test_id(
        "clean-filters"
    )

    botao.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    expect(botao).to_be_enabled(
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page)

    log("Clicando em Limpar filtros...")
    clicar_com_fallback(
        page,
        botao,
        "Limpar filtros",
    )

    page.wait_for_timeout(
        ESPERA_DASHBOARD
    )


def abrir_area_direta(
    page: Page,
    nome_area: str,
    url_area: str,
):
    log(f"Abrindo diretamente: {nome_area}")

    try:
        page.goto(
            url_area,
            wait_until="domcontentloaded",
            timeout=TIMEOUT_NORMAL,
        )

    except PlaywrightTimeoutError:
        if url_area not in page.url:
            raise

        log(
            "A página continua carregando recursos "
            "em segundo plano."
        )

    page.bring_to_front()

    caminho_esperado = url_area.split(
        "extranet.grupoboticario.com.br",
        1,
    )[-1]

    limite = time.time() + (
        TIMEOUT_NORMAL / 1000
    )

    while time.time() < limite:
        campo_usuario = page.get_by_role(
            "textbox",
            name="Usuário",
        )

        try:
            if campo_usuario.is_visible():
                log("A sessão expirou. Refazendo o login...")
                fazer_login(page)

                page.goto(
                    url_area,
                    wait_until="domcontentloaded",
                    timeout=TIMEOUT_NORMAL,
                )

                break

        except Exception:
            pass

        if caminho_esperado in page.url:
            break

        page.wait_for_timeout(1_000)

    if caminho_esperado not in page.url:
        raise TimeoutError(
            f"A área {nome_area} não foi aberta. "
            f"Página atual: {page.url}"
        )

    page.wait_for_timeout(
        ESPERA_DASHBOARD
    )

    # O aviso costuma surgir somente depois que o dashboard termina
    # de montar. Por isso ele deve ser tratado após a espera principal.
    fechar_aviso_notificacoes(
        page,
        timeout=5_000,
    )

    log(f"Área carregada: {nome_area}")


def localizar_dialogo_planilha(page: Page) -> Locator:
    dialogo = page.get_by_role(
        "dialog",
        name="Exportar Planilha",
    ).last

    dialogo.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    return dialogo


def localizar_checkbox_por_texto(
    dialogo: Locator,
    texto: str,
) -> Locator:
    texto_opcao = dialogo.get_by_text(
        texto,
        exact=True,
    ).last

    texto_opcao.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    # Algumas áreas usam um input HTML; outras usam um controle
    # personalizado com role="checkbox" e sem nome acessível.
    # Por isso, primeiro procuramos o controle dentro do mesmo
    # item visual que contém o texto do relatório.
    seletores = [
        texto_opcao.locator(
            "xpath=ancestor-or-self::*[@role='checkbox'][1]"
        ),
        texto_opcao.locator(
            "xpath=ancestor::*["
            ".//input[@type='checkbox'] or "
            ".//*[@role='checkbox']"
            "][1]"
        ).locator(
            "input[type='checkbox'], [role='checkbox']"
        ),
        dialogo.locator(
            "label",
            has_text=texto,
        ).locator(
            "input[type='checkbox'], [role='checkbox']"
        ),
    ]

    for candidato in seletores:
        if candidato.count() > 0:
            return candidato.first

    # Última tentativa para páginas em que o checkbox possui um
    # label acessível corretamente associado.
    checkbox_nomeado = dialogo.get_by_role(
        "checkbox",
        name=texto,
        exact=True,
    )

    try:
        checkbox_nomeado.wait_for(
            state="attached",
            timeout=10_000,
        )
        return checkbox_nomeado.first

    except PlaywrightTimeoutError as erro:
        quantidade = dialogo.locator(
            "input[type='checkbox'], [role='checkbox']"
        ).count()

        raise RuntimeError(
            f"Não foi possível associar o checkbox ao relatório "
            f"'{texto}'. Controles encontrados no modal: "
            f"{quantidade}."
        ) from erro


def normalizar_controle_checkbox(
    controle: Locator,
) -> Locator:
    """Retorna o input/controle clicável, mesmo se o CSS apontar para o bloco."""
    controle = controle.first

    tag = controle.evaluate(
        "elemento => elemento.tagName.toLowerCase()"
    )
    tipo = controle.get_attribute("type")
    papel = controle.get_attribute("role")

    if (
        (tag == "input" and tipo == "checkbox")
        or papel == "checkbox"
    ):
        return controle

    descendente = controle.locator(
        "input[type='checkbox'], [role='checkbox']"
    )

    if descendente.count() > 0:
        return descendente.first

    return controle


def controle_checkbox_marcado(
    controle: Locator,
) -> bool:
    return bool(
        controle.evaluate(
            """
            (elemento) => {
                const controle = elemento.matches(
                    "input[type='checkbox'], [role='checkbox']"
                )
                    ? elemento
                    : elemento.querySelector(
                        "input[type='checkbox'], [role='checkbox']"
                    );

                if (!controle) {
                    return false;
                }

                if (
                    controle.tagName.toLowerCase() === "input" &&
                    controle.type === "checkbox"
                ) {
                    return controle.checked;
                }

                if (controle.getAttribute("aria-checked") === "true") {
                    return true;
                }

                if (controle.getAttribute("data-state") === "checked") {
                    return true;
                }

                return Boolean(
                    controle.closest(
                        ".ant-checkbox-checked, " +
                        ".ant-checkbox-wrapper-checked"
                    )
                );
            }
            """
        )
    )


def confirmar_checkbox_marcado(
    page: Page,
    controle: Locator,
    texto: str,
):
    limite = time.time() + 15

    while time.time() < limite:
        if controle_checkbox_marcado(controle):
            log(f"Marcado com sucesso: {texto}")
            return

        page.wait_for_timeout(500)

    raise RuntimeError(
        f"O checkbox '{texto}' foi localizado, mas não ficou marcado."
    )


def marcar_checkbox_modal(
    page: Page,
    dialogo: Locator,
    texto: str,
    seletor_css: str | None = None,
):
    log(f"Marcando: {texto}")

    checkbox = None

    if seletor_css:
        checkbox_mapeado = dialogo.locator(
            seletor_css
        )

        if checkbox_mapeado.count() > 0:
            checkbox = normalizar_controle_checkbox(
                checkbox_mapeado
            )

    if checkbox is None:
        checkbox = localizar_checkbox_por_texto(
            dialogo,
            texto,
        )

    checkbox = normalizar_controle_checkbox(
        checkbox
    )

    checkbox.wait_for(
        state="attached",
        timeout=TIMEOUT_NORMAL,
    )

    if not controle_checkbox_marcado(checkbox):
        tag = checkbox.evaluate(
            "elemento => elemento.tagName.toLowerCase()"
        )
        tipo = checkbox.get_attribute("type")

        if tag == "input" and tipo == "checkbox":
            checkbox.check(force=True)
        else:
            checkbox.click(force=True)

    confirmar_checkbox_marcado(
        page,
        checkbox,
        texto,
    )


def baixar_exportacao_modal(
    page: Page,
    relatorios: list[tuple[str, str | None]],
    nome_arquivo: str,
    pasta_destino: Path = PASTA_DOWNLOADS,
):
    botao_exportar = esperar_botao_exportar(page)

    esperar_antes(page)
    clicar_com_fallback(
        page,
        botao_exportar,
        "Exportar",
    )

    dialogo = localizar_dialogo_planilha(page)

    for texto, seletor_css in relatorios:
        esperar_antes(page, 2_000)
        marcar_checkbox_modal(
            page,
            dialogo,
            texto,
            seletor_css,
        )

    botao_modal = dialogo.get_by_test_id(
        "btn-export-modal"
    )

    botao_modal.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    expect(botao_modal).to_be_enabled(
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page)

    log(f"Baixando: {nome_arquivo}")

    with page.expect_download(
        timeout=TIMEOUT_RELATORIO,
    ) as download_info:
        botao_modal.click()

    salvar_download(
        download_info.value,
        nome_arquivo,
        pasta_destino,
    )


def baixar_exportacoes_em_lote(
    page: Page,
    relatorios: list[tuple[str, str | None, str]],
    pasta_destino: Path = PASTA_DOWNLOADS,
):
    """Marca tudo uma vez e captura cada arquivo separadamente."""
    botao_exportar = esperar_botao_exportar(page)

    esperar_antes(page)
    clicar_com_fallback(
        page,
        botao_exportar,
        "Exportar relatórios em lote",
    )

    dialogo = localizar_dialogo_planilha(page)

    for texto, seletor_css, _ in relatorios:
        log(f"Marcando: {texto}")
        esperar_antes(page, 1_000)
        marcar_checkbox_modal(
            page,
            dialogo,
            texto,
            seletor_css,
        )

    botao_modal = dialogo.get_by_test_id(
        "btn-export-modal"
    )

    botao_modal.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    expect(botao_modal).to_be_enabled(
        timeout=TIMEOUT_NORMAL,
    )

    downloads = []

    def registrar_download(download):
        downloads.append(download)
        log(
            "Download recebido: "
            f"{len(downloads)}/{len(relatorios)}"
        )

    page.on("download", registrar_download)

    try:
        log(
            f"Exportando {len(relatorios)} planilhas de uma vez..."
        )

        esperar_antes(page)
        clicar_com_fallback(
            page,
            botao_modal,
            "Exportar Seleção",
        )

        limite = time.time() + (
            TIMEOUT_RELATORIO / 1000
        )

        while (
            len(downloads) < len(relatorios)
            and time.time() < limite
        ):
            page.wait_for_timeout(500)

        if len(downloads) != len(relatorios):
            raise TimeoutError(
                f"Eram esperados {len(relatorios)} downloads, "
                f"mas foram recebidos {len(downloads)}."
            )

    finally:
        page.remove_listener(
            "download",
            registrar_download,
        )

    for download, (_, _, nome_arquivo) in zip(
        downloads,
        relatorios,
    ):
        salvar_download(
            download,
            nome_arquivo,
            pasta_destino,
        )


def abrir_painel_exportacao_treinamentos(
    page: Page,
) -> Locator:
    botao_exportar = esperar_botao_exportar(page)

    esperar_antes(page)
    clicar_com_fallback(
        page,
        botao_exportar,
        "Exportar",
    )

    titulo = page.get_by_text(
        "Exportar dados",
        exact=True,
    ).last

    titulo.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    return titulo


def marcar_checkbox_treinamentos(page: Page):
    """
    O novo mapeamento mostrou que o primeiro checkbox de
    Treinamentos não possui nome acessível. O painel é inserido
    no fim do DOM, então o último checkbox é o da exportação.
    """
    log("Marcando a seção de Treinamentos...")

    checkbox = page.get_by_role(
        "checkbox"
    ).last

    checkbox.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    if not checkbox.is_checked():
        checkbox.check(force=True)

    expect(checkbox).to_be_checked(
        timeout=TIMEOUT_NORMAL,
    )


def esperar_novo_salvar_dados(
    page: Page,
    quantidade_anterior: int,
) -> Locator:
    log("Aguardando a nova exportação ficar pronta...")

    botoes_salvar = page.get_by_text(
        "Salvar dados",
        exact=True,
    )

    limite = time.time() + (
        TIMEOUT_RELATORIO / 1000
    )

    while time.time() < limite:
        quantidade_atual = botoes_salvar.count()

        if quantidade_atual > quantidade_anterior:
            # O vídeo mostrou que a exportação nova entra no topo.
            botao_novo = botoes_salvar.first

            botao_novo.wait_for(
                state="visible",
                timeout=TIMEOUT_NORMAL,
            )

            expect(botao_novo).to_be_enabled(
                timeout=TIMEOUT_NORMAL,
            )

            log("A nova exportação ficou pronta.")

            return botao_novo

        page.wait_for_timeout(3_000)

    raise TimeoutError(
        "A nova planilha não ficou pronta no tempo esperado."
    )


def baixar_exportacao_treinamentos(
    page: Page,
    nome_arquivo: str,
    pasta_destino: Path = PASTA_DOWNLOADS,
):
    abrir_painel_exportacao_treinamentos(page)

    esperar_antes(page)
    marcar_checkbox_treinamentos(page)

    botao_modal = page.get_by_test_id(
        "btn-export-modal"
    )

    botao_modal.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    expect(botao_modal).to_be_enabled(
        timeout=TIMEOUT_NORMAL,
    )

    quantidade_anterior = page.get_by_text(
        "Salvar dados",
        exact=True,
    ).count()

    esperar_antes(page)

    log("Solicitando a geração da planilha...")
    botao_modal.click()

    botao_salvar = esperar_novo_salvar_dados(
        page,
        quantidade_anterior,
    )

    esperar_antes(page)

    log(f"Baixando: {nome_arquivo}")

    with page.expect_download(
        timeout=TIMEOUT_RELATORIO,
    ) as download_info:
        botao_salvar.click()

    salvar_download(
        download_info.value,
        nome_arquivo,
        pasta_destino,
    )


def fechar_painel_exportacao_treinamentos(
    page: Page,
):
    log("Fechando o painel Exportar dados...")

    titulo = page.get_by_text(
        "Exportar dados",
        exact=True,
    ).last

    if titulo.count() == 0:
        return

    try:
        botao_fechar = page.locator(
            ".ant-drawer-close"
        ).last

        if botao_fechar.count() > 0:
            esperar_antes(page, 2_000)
            botao_fechar.click()
        else:
            page.keyboard.press("Escape")

        titulo.wait_for(
            state="hidden",
            timeout=20_000,
        )

    except PlaywrightTimeoutError:
        page.keyboard.press("Escape")
        page.wait_for_timeout(2_000)


def clicar_filtro_por_texto(
    page: Page,
    texto: str,
):
    opcao = page.get_by_text(
        texto,
        exact=True,
    ).first

    opcao.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page)
    opcao.click()

    page.wait_for_timeout(
        ESPERA_DASHBOARD
    )


# ============================================================
# LOGIN
# ============================================================

def fazer_login(page: Page):
    log("Verificando login...")

    campo_usuario = page.get_by_role(
        "textbox",
        name="Usuário",
    )

    try:
        campo_usuario.wait_for(
            state="visible",
            timeout=20_000,
        )

    except PlaywrightTimeoutError:
        log("Sessão já autenticada.")
        return

    esperar_antes(page)

    log("Preenchendo usuário...")
    campo_usuario.fill(USUARIO)

    campo_senha = page.get_by_role(
        "textbox",
        name="Password",
    )

    campo_senha.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page)

    log("Preenchendo senha...")
    campo_senha.fill(SENHA)

    botao_entrar = page.get_by_role(
        "button",
        name="Entrar",
    )

    botao_entrar.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page)

    log("Clicando em Entrar...")
    botao_entrar.click()

    menu = page.get_by_role(
        "button",
        name="Gestão de resultados",
    )

    menu.wait_for(
        state="visible",
        timeout=120_000,
    )

    page.wait_for_timeout(5_000)
    log("Login concluído.")


# ============================================================
# 1 — SERVIÇOS EM LOJA
# ============================================================

def baixar_servicos_em_loja(page: Page):
    log("========== 1. SERVIÇOS EM LOJA ==========")

    abrir_area_direta(
        page,
        "Serviços em Loja",
        URL_SERVICOS_EM_LOJA,
    )

    limpar_filtros(page)

    pasta_destino = preparar_periodo(page)

    baixar_exportacao_modal(
        page,
        [
            (
                "Serviços realizados por PDV e Consultor",
                None,
            ),
        ],
        "ServicosRealizadosPorPDVConsultor",
        pasta_destino,
    )

    log("Serviços em Loja concluído.")


# ============================================================
# 2 — LOJA DIGITAL
# ============================================================

def baixar_loja_digital(page: Page):
    log("========== 2. LOJA DIGITAL ==========")

    abrir_area_direta(
        page,
        "Loja Digital",
        URL_LOJA_DIGITAL,
    )

    limpar_filtros(page)

    pasta_destino = preparar_periodo(page)

    baixar_exportacao_modal(
        page,
        [
            (
                "Performance por PDV/Consultor",
                "#consultantPerformance",
            ),
        ],
        "PerformancePorPDVConsultor",
        pasta_destino,
    )

    log("Loja Digital concluído.")


# ============================================================
# 3 — TREINAMENTOS IAF / FORÇA DE VENDAS
# ============================================================

def baixar_treinamentos_forca_vendas(page: Page):
    log(
        "========== 3. TREINAMENTOS IAF "
        "FORÇA DE VENDAS =========="
    )

    abrir_area_direta(
        page,
        "Treinamentos",
        URL_TREINAMENTOS_FORCA_VENDAS,
    )

    pasta_destino = preparar_data_final_treinamentos(page)

    botao_pdv = page.get_by_role(
        "button",
        name="PDV",
        exact=True,
    )

    botao_pdv.wait_for(
        state="visible",
        timeout=TIMEOUT_TREINAMENTOS,
    )

    esperar_antes(page)

    log("Selecionando a visão PDV...")
    botao_pdv.click()

    page.wait_for_timeout(
        ESPERA_DASHBOARD
    )

    baixar_exportacao_treinamentos(
        page,
        "TreinamentosIAFForcaVendasPDV",
        pasta_destino,
    )

    fechar_painel_exportacao_treinamentos(page)

    log("Treinamentos IAF Força de Vendas concluído.")


# ============================================================
# 4 — TREINAMENTOS IAF POR CICLO
# ============================================================

def baixar_treinamentos_iaf_ciclo(page: Page):
    log(
        "========== 4. TREINAMENTOS IAF "
        "POR CICLO =========="
    )

    abrir_area_direta(
        page,
        "Treinamentos IAF por ciclo",
        URL_TREINAMENTOS_IAF_CICLO,
    )

    baixar_exportacao_treinamentos(
        page,
        "TreinamentosIAFPorCiclo",
    )

    fechar_painel_exportacao_treinamentos(page)

    log("Treinamentos IAF por ciclo concluído.")


# ============================================================
# 5 — ID CLIENTE
# ============================================================

def baixar_id_cliente(page: Page):
    log("========== 5. ID CLIENTE ==========")

    abrir_area_direta(
        page,
        "ID Cliente",
        URL_ID_CLIENTE,
    )

    # Novo mapeamento gravado especificamente na área ID Cliente:
    # Agora não -> Limpar filtros -> Exportar -> #indicators -> Exportar.
    clicar_se_aparecer(
        page,
        page.get_by_role(
            "button",
            name="Agora não",
        ),
        timeout=2_000,
    )

    limpar_filtros(page)

    pasta_destino = preparar_periodo(page)

    botao_exportar = esperar_botao_exportar(page)

    esperar_antes(page)

    log("Abrindo a exportação de ID Cliente...")
    clicar_com_fallback(
        page,
        botao_exportar,
        "Exportar em ID Cliente",
    )

    modal = page.get_by_role(
        "dialog",
        name="Exportar Planilha",
    ).last

    modal.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    checkbox_indicadores = modal.locator("#indicators")
    checkbox_indicadores.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page)

    log("Marcando: Indicadores ID Cliente")

    if not checkbox_indicadores.is_checked():
        clicar_com_fallback(
            page,
            checkbox_indicadores,
            "Indicadores ID Cliente",
        )

    expect(checkbox_indicadores).to_be_checked(
        timeout=10_000,
    )

    botao_modal = modal.get_by_test_id(
        "btn-export-modal"
    )

    botao_modal.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    expect(botao_modal).to_be_enabled(
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page)

    log("Baixando: Indicadores ID Cliente")

    with page.expect_download(
        timeout=TIMEOUT_RELATORIO,
    ) as download_info:
        clicar_com_fallback(
            page,
            botao_modal,
            "Exportar Planilha",
        )

    salvar_download(
        download_info.value,
        "IndicadoresIDCliente",
        pasta_destino,
    )

    log("ID Cliente concluído.")


# ============================================================
# 6 — AÇÃO DE FLUXO
# ============================================================

def selecionar_campanhas_acao_de_fluxo(
    page: Page,
    campo: Locator,
    campanhas: list[str] | None,
):
    """Deixa marcadas as campanhas pedidas (None = todas). O filtro é
    uma multisseleção que não aceita digitação: rola a lista virtualizada
    de cima para baixo e clica nas opções."""
    remover = campo.locator(".ant-select-selection-item-remove")

    while remover.count() > 0:
        remover.first.click()
        page.wait_for_timeout(500)

    campo.click()

    dropdown = page.locator(".ant-select-dropdown:visible")
    lista = dropdown.locator(".rc-virtual-list-holder").first
    lista.wait_for(state="visible", timeout=TIMEOUT_NORMAL)
    lista.evaluate("el => { el.scrollTop = 0; }")
    page.wait_for_timeout(500)

    pedidas = None if campanhas is None else set(campanhas)
    marcadas: list[str] = []
    vistas: list[str] = []

    for _ in range(300):
        itens = dropdown.locator(".ant-select-item-option").evaluate_all(
            """els => els.map(e => [
                e.getAttribute('title'),
                e.classList.contains('ant-select-item-option-selected'),
            ])"""
        )

        for titulo_bruto, selecionada in itens:
            if not titulo_bruto:
                continue

            # O title das opções vem com espaço no final.
            titulo = titulo_bruto.strip()

            if titulo not in vistas:
                vistas.append(titulo)

            if titulo in marcadas:
                continue

            if pedidas is not None and titulo not in pedidas:
                continue

            if not selecionada:
                log(f"Selecionando campanha: {titulo}")
                dropdown.get_by_title(
                    titulo_bruto,
                    exact=True,
                ).first.click()
                page.wait_for_timeout(1_000)

            marcadas.append(titulo)

        if pedidas is not None and pedidas.issubset(marcadas):
            break

        topo, total, visivel = lista.evaluate(
            "el => [el.scrollTop, el.scrollHeight, el.clientHeight]"
        )

        if topo + visivel >= total - 2:
            break

        lista.evaluate("el => { el.scrollTop += el.clientHeight - 20; }")
        page.wait_for_timeout(400)

    if pedidas is not None:
        faltantes = sorted(pedidas - set(marcadas))

        if faltantes:
            raise RuntimeError(
                f"Campanha(s) não encontrada(s): {faltantes}. "
                f"Disponíveis: {vistas}"
            )

    page.keyboard.press("Escape")
    log(f"Campanhas marcadas: {len(marcadas)}")


def baixar_acao_de_fluxo(page: Page):
    log("========== 6. AÇÃO DE FLUXO ==========")

    # CAMPANHAS="Nome A;Nome B" marca essas campanhas; CAMPANHAS="todas"
    # marca todas; sem a variável, mantém a campanha padrão do site.
    texto_campanhas = os.getenv("CAMPANHAS", "").strip()

    abrir_area_direta(
        page,
        "Ação de Fluxo",
        URL_ACAO_DE_FLUXO,
    )

    campo_campanha = page.locator(
        ".ant-select-selection-overflow"
    ).first

    campo_campanha.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    pasta_destino = PASTA_DOWNLOADS

    if texto_campanhas:
        esperar_antes(page)

        if texto_campanhas.lower() == "todas":
            campanhas = None
            rotulo = "todas"
        else:
            campanhas = [
                nome.strip()
                for nome in texto_campanhas.split(";")
                if nome.strip()
            ]
            rotulo = "_".join(campanhas)

        selecionar_campanhas_acao_de_fluxo(
            page,
            campo_campanha,
            campanhas,
        )

        rotulo = re.sub(r"[^\w-]+", "_", rotulo)[:80]
        pasta_destino = (
            PASTA_DOWNLOADS.parent
            / "dados_brutos periodos"
            / f"acao_de_fluxo_{rotulo}"
        )
        pasta_destino.mkdir(parents=True, exist_ok=True)
        log(f"Pasta de destino: {pasta_destino}")

    page.get_by_text(
        re.compile(r"^Visão Geral"),
    ).first.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    page.wait_for_timeout(
        ESPERA_DASHBOARD
    )

    baixar_exportacao_modal(
        page,
        [
            (
                "Performance por PDV ou Consultor(a)",
                None,
            ),
        ],
        "PerformanceAcaoDeFluxo",
        pasta_destino,
    )

    log("Ação de Fluxo concluído.")


# ============================================================
# 7 — PROGRAMA FIDELIDADE
# ============================================================

def baixar_programa_fidelidade(page: Page):
    log("========== 7. PROGRAMA FIDELIDADE ==========")

    abrir_area_direta(
        page,
        "Programa Fidelidade",
        URL_PROGRAMA_FIDELIDADE,
    )

    pasta_destino = preparar_periodo(page)

    baixar_exportacoes_em_lote(
        page,
        [
            (
                "Distribuição do % de Boletos com resgate",
                "#ticketRescueDistribution",
                "DistribuicaoBoletosComResgate",
            ),
            (
                "Distribuição Penetração Desafio Fidelidade",
                "#distributionPenetrationChallengeLoyalty",
                "PenetracaoDesafioFidelidade",
            ),
        ],
        pasta_destino,
    )

    log("Programa Fidelidade concluído.")


# ============================================================
# 8 — CANAL LOJA
# ============================================================

def localizar_radio_canal_loja(
    page: Page,
    texto: str,
) -> Locator:
    radio = page.get_by_role(
        "radio",
        name=texto,
        exact=True,
    )

    if radio.count() > 0:
        return radio.first

    rotulo = page.locator("label").filter(
        has_text=re.compile(
            rf"^\s*{re.escape(texto)}\s*$",
            re.IGNORECASE,
        )
    ).first

    radio = rotulo.locator(
        'input[type="radio"]'
    )

    if radio.count() == 0:
        raise RuntimeError(
            f"Filtro de opção não encontrado: {texto}"
        )

    return radio.first


def selecionar_radio_canal_loja(
    page: Page,
    texto: str,
):
    log(f"Selecionando {texto}...")

    radio = localizar_radio_canal_loja(
        page,
        texto,
    )

    radio.scroll_into_view_if_needed(
        timeout=TIMEOUT_NORMAL,
    )

    if not radio.is_checked():
        radio.check(force=True)

        # Cada alteração refaz os componentes do dashboard.
        page.wait_for_timeout(
            ESPERA_DASHBOARD
        )

    radio_atualizado = localizar_radio_canal_loja(
        page,
        texto,
    )

    expect(radio_atualizado).to_be_checked(
        timeout=TIMEOUT_NORMAL,
    )


MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def ler_periodo_ambiente():
    """Lê PERIODO_INICIO/PERIODO_FIM (dd/mm/aaaa). Devolve (inicio, fim)
    como datetime, ou None se não definidos (mantém o período padrão)."""
    texto_inicio = os.getenv("PERIODO_INICIO", "").strip()
    texto_fim = os.getenv("PERIODO_FIM", "").strip()

    if not texto_inicio or not texto_fim:
        return None

    inicio = datetime.strptime(texto_inicio, "%d/%m/%Y")
    fim = datetime.strptime(texto_fim, "%d/%m/%Y")

    if fim < inicio:
        raise ValueError(
            "PERIODO_FIM não pode ser anterior a PERIODO_INICIO."
        )

    return inicio, fim


def clicar_dia_calendario(page: Page, data: datetime):
    """Navega o calendário (react-date-range) até o mês/ano e clica no
    dia. Usa os seletores de mês e ano do topo, não a posição na tela."""
    page.locator(".rdrMonthPicker select").select_option(
        value=str(data.month - 1)
    )
    page.locator(".rdrYearPicker select").select_option(
        value=str(data.year)
    )
    page.wait_for_timeout(1_000)

    nome_mes = MESES_PT[data.month - 1]

    meses = page.locator(".rdrMonth").filter(
        has=page.locator(
            ".rdrMonthName",
            has_text=re.compile(f"^{nome_mes}", re.IGNORECASE),
        )
    )

    if meses.count() > 1:
        com_ano = meses.filter(
            has=page.locator(
                ".rdrMonthName",
                has_text=str(data.year),
            )
        )
        if com_ano.count() > 0:
            meses = com_ano

    dia = (
        meses.first
        .locator("button.rdrDay:not(.rdrDayPassive)")
        .filter(has_text=re.compile(f"^{data.day}$"))
        .first
    )

    dia.scroll_into_view_if_needed(timeout=TIMEOUT_NORMAL)
    dia.click(timeout=TIMEOUT_NORMAL)


def selecionar_periodo_calendario(
    page: Page,
    inicio: datetime,
    fim: datetime,
):
    """Define o 'Período atual' (intervalo): 1º clique = início,
    2º clique = fim. Depois dispensa o aviso 'Agora não', se aparecer."""
    log(
        "Selecionando período: "
        f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}"
    )

    campo = page.get_by_text(
        re.compile(r"Per[ií]odo atual:")
    ).first
    campo.wait_for(state="visible", timeout=TIMEOUT_NORMAL)

    esperar_antes(page)
    campo.click()

    page.locator(".rdrMonthPicker select").wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    clicar_dia_calendario(page, inicio)
    esperar_antes(page, 1_000)
    clicar_dia_calendario(page, fim)

    agora_nao = page.get_by_role("button", name="Agora não")
    try:
        agora_nao.first.wait_for(state="visible", timeout=8_000)
        agora_nao.first.click()
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(ESPERA_DASHBOARD)


def pasta_destino_periodo(periodo) -> Path:
    """Sem período definido usa 'dados_brutos'; com período, separa em
    'dados_brutos periodos/<inicio>_a_<fim>' para não misturar com o
    diário."""
    if periodo is None:
        return PASTA_DOWNLOADS

    inicio, fim = periodo
    pasta = (
        PASTA_DOWNLOADS.parent
        / "dados_brutos periodos"
        / f"{inicio:%Y-%m-%d}_a_{fim:%Y-%m-%d}"
    )
    pasta.mkdir(parents=True, exist_ok=True)

    return pasta


def preparar_data_final_treinamentos(page: Page) -> Path:
    """Treinamentos tem só 'Data de conclusão até:' (o início é sempre o
    começo do ano). Usa PERIODO_FIM; sem ele, mantém a data padrão."""
    texto_fim = os.getenv("PERIODO_FIM", "").strip()

    if not texto_fim:
        log("PERIODO_FIM não definido: mantendo a data padrão.")
        return PASTA_DOWNLOADS

    fim = datetime.strptime(texto_fim, "%d/%m/%Y")

    pasta = (
        PASTA_DOWNLOADS.parent
        / "dados_brutos periodos"
        / f"treinamentos_ate_{fim:%Y-%m-%d}"
    )
    pasta.mkdir(parents=True, exist_ok=True)
    log(f"Pasta de destino: {pasta}")
    log(f"Selecionando data de conclusão até: {fim:%d/%m/%Y}")

    campo = page.get_by_text(
        "Data de conclusão até:",
        exact=True,
    ).first
    campo.wait_for(state="visible", timeout=TIMEOUT_NORMAL)

    esperar_antes(page)
    campo.click()

    page.locator(".rdrMonthPicker select").wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    clicar_dia_calendario(page, fim)

    agora_nao = page.get_by_role("button", name="Agora não")
    try:
        agora_nao.first.wait_for(state="visible", timeout=8_000)
        agora_nao.first.click()
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(ESPERA_DASHBOARD)

    return pasta


def preparar_periodo(page: Page) -> Path:
    """Aplica PERIODO_INICIO/PERIODO_FIM (se definidos) e devolve a pasta
    de destino. Deve rodar depois de limpar_filtros(), que volta o
    calendário ao período padrão."""
    periodo = ler_periodo_ambiente()
    pasta_destino = pasta_destino_periodo(periodo)
    log(f"Pasta de destino: {pasta_destino}")

    if periodo is not None:
        selecionar_periodo_calendario(page, *periodo)

    return pasta_destino


def baixar_exportacoes_canal_loja(
    page: Page,
    pasta_destino: Path = PASTA_DOWNLOADS,
):
    relatorios = [
        (
            "Indicadores de loja",
            None,
            "IndicadoresLoja",
        ),
        (
            "Categorias Loja - Cuidados Faciais + Botik (IAF)",
            None,
            "CategoriasLojaCuidadosFaciaisBotik",
        ),
        (
            "Boleto promocional",
            "#promotionalCoupon",
            "BoletoPromocional",
        ),
        (
            "Boleto turbinado",
            None,
            "BoletoTurbinado",
        ),
    ]

    baixar_exportacoes_em_lote(
        page,
        relatorios,
        pasta_destino,
    )


def baixar_canal_loja(page: Page):
    log("========== 8. CANAL LOJA ==========")

    abrir_area_direta(
        page,
        "Canal Loja",
        URL_CANAL_LOJA,
    )

    log("Abrindo Detalhamento Geral...")
    aba_detalhamento = page.get_by_role(
        "tab",
        name="Detalhamento Geral",
        exact=True,
    )

    if aba_detalhamento.count() == 0:
        aba_detalhamento = page.get_by_text(
            "Detalhamento Geral",
            exact=True,
        ).first

    aba_detalhamento.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    clicar_com_fallback(
        page,
        aba_detalhamento,
        "Detalhamento Geral",
    )

    page.wait_for_url(
        re.compile(r"/store-view/general(?:\?|$)"),
        timeout=TIMEOUT_NORMAL,
    )

    page.wait_for_timeout(
        ESPERA_DASHBOARD
    )

    # Ordem registrada no vídeo de 14/08/2026.
    selecionar_radio_canal_loja(
        page,
        "Próprias e Adquiridas",
    )

    selecionar_radio_canal_loja(
        page,
        "Receita GMV",
    )

    selecionar_radio_canal_loja(
        page,
        "Ano anterior fiscal",
    )

    periodo = ler_periodo_ambiente()
    pasta_destino = pasta_destino_periodo(periodo)
    log(f"Pasta de destino: {pasta_destino}")

    if periodo is not None:
        selecionar_periodo_calendario(page, *periodo)

    baixar_exportacoes_canal_loja(page, pasta_destino)

    log("Canal Loja concluído.")


# ============================================================
# 9 — VENDA DIRETA: MONITORAMENTO DE BASE (Make, Cabelos, Multimarca)
# ============================================================

def selecionar_pdv_venda_direta(
    page: Page,
    codigo_er: str,
):
    """Seleciona um único ER no filtro 'Unidade de negócio'.

    Seletor confirmado via mapeamento.py (gravação real em
    09/09/2026). É um combobox de MÚLTIPLA seleção (checkbox por
    ER) — os ERs marcados anteriormente ficam acumulados se não
    for chamado limpar_filtros(page) antes de cada seleção nova
    (confirmado visualmente: chips "13481 x 13483 x ..." se
    acumulando). A opção da lista tem atributo title com espaço no
    final (ex.: "13483 ").
    """
    log(f"Selecionando PDV: {codigo_er}")

    campo = page.locator(
        "div:nth-child(7) > .mf-gi-core-c-gsXidR "
        "> .ant-select > .ant-select-selector"
    )

    campo.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page)
    campo.click()

    opcao = page.get_by_title(
        f"{codigo_er} ",
        exact=True,
    )

    if opcao.count() == 0:
        opcao = page.get_by_title(
            codigo_er,
            exact=True,
        )

    if opcao.count() == 0:
        opcao = page.get_by_text(
            codigo_er,
            exact=True,
        ).nth(1)

    opcao.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page, 1_000)
    opcao.click()

    page.wait_for_timeout(
        ESPERA_DASHBOARD
    )


def fechar_modal_exportacao(page: Page):
    """Fecha o modal 'Exportar Planilha' (ícone X) antes de trocar
    o filtro de PDV. Confirmado como necessário via mapeamento.py:
    sem fechar o modal, o clique seguinte no filtro não aplicava."""
    try:
        dialogo = page.get_by_role(
            "dialog",
            name="Exportar Planilha",
        ).last

        if dialogo.count() == 0:
            return

        botao_fechar = dialogo.locator(
            ".anticon-close"
        ).last

        if botao_fechar.count() > 0:
            botao_fechar.click()
        else:
            page.keyboard.press("Escape")

        dialogo.wait_for(
            state="hidden",
            timeout=10_000,
        )

    except PlaywrightTimeoutError:
        page.keyboard.press("Escape")
        page.wait_for_timeout(1_000)

    except Exception:
        pass


def pasta_destino_venda_direta() -> Path:
    """Sem CICLO_INICIO, usa a pasta diária ('iaf vd'). Com ciclo
    definido, separa em 'iaf vd ciclos/<ciclo>' para não ser confundido
    com os dados do dia pelo vd.py / atualizar_vd_hubbia.py."""
    inicio = os.getenv("CICLO_INICIO", "").strip()

    if not inicio:
        return PASTA_DOWNLOADS_VD

    fim = os.getenv("CICLO_FIM", "").strip() or inicio

    nome = (
        f"ciclo_{inicio}"
        if inicio == fim
        else f"ciclos_{inicio}_a_{fim}"
    )

    pasta = PASTA_DOWNLOADS_VD.parent / "iaf vd ciclos" / nome
    pasta.mkdir(parents=True, exist_ok=True)

    return pasta


def selecionar_ciclos_venda_direta(page: Page):
    """Aplica o intervalo de ciclos definido em CICLO_INICIO/CICLO_FIM.

    O seletor 'Ciclo atual:' é um intervalo (clica no início e depois
    no fim); para um ciclo só, clica-se no mesmo botão duas vezes.
    Sem as variáveis, não mexe no filtro (ciclo atual do site).
    Precisa rodar depois de limpar_filtros(), que volta ao ciclo atual.
    """
    inicio = os.getenv("CICLO_INICIO", "").strip()
    fim = os.getenv("CICLO_FIM", "").strip() or inicio

    if not inicio:
        return

    log(f"Selecionando ciclos: {inicio} a {fim}")

    campo = page.get_by_placeholder("Ciclo atual:")
    campo.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page)
    campo.click()

    botao_inicio = page.get_by_role(
        "button",
        name=f"Ciclo {inicio}",
        exact=True,
    )
    botao_inicio.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )
    botao_inicio.click()

    esperar_antes(page, 1_000)
    page.get_by_role(
        "button",
        name=f"Ciclo {fim}",
        exact=True,
    ).click()

    page.wait_for_timeout(
        ESPERA_DASHBOARD
    )


def baixar_venda_direta_monitoramento_base(page: Page):
    log(
        "========== 9. VENDA DIRETA - "
        "MONITORAMENTO DE BASE =========="
    )

    abrir_area_direta(
        page,
        "Venda Direta - Monitoramento de Base",
        URL_MONITORAMENTO_BASE_VD,
    )

    pasta_destino = pasta_destino_venda_direta()
    log(f"Pasta de destino: {pasta_destino}")

    selecionar_ciclos_venda_direta(page)

    log("Exportando visão geral (todos os ERs)...")
    baixar_exportacoes_em_lote(
        page,
        RELATORIOS_MONITORAMENTO_BASE + RELATORIO_MONITORAMENTO_BASE_GERAL,
        pasta_destino,
    )

    fechar_modal_exportacao(page)

    # ERS_VD limita os ERs processados (ex.: "13481" ou "13481,13483");
    # "nenhum" roda só a visão geral. Sem a variável, roda todos.
    filtro_ers = os.getenv("ERS_VD", "").strip().lower()

    if not filtro_ers:
        ers_processar = ERS_VENDA_DIRETA
    elif filtro_ers == "nenhum":
        ers_processar = []
    else:
        ers_processar = [
            er.strip() for er in filtro_ers.split(",") if er.strip()
        ]

    for codigo_er in ers_processar:
        try:
            # 'Unidade de negócio' é multisseleção: acumula ERs se
            # não limpar antes de marcar o próximo.
            limpar_filtros(page)
            selecionar_ciclos_venda_direta(page)
            selecionar_pdv_venda_direta(page, codigo_er)

            log(f"Exportando ER {codigo_er}...")
            baixar_exportacoes_em_lote(
                page,
                RELATORIOS_MONITORAMENTO_BASE,
                pasta_destino,
            )

            fechar_modal_exportacao(page)

        except Exception as erro:
            # Um ER com problema não deve derrubar os outros 5.
            log(f"Falha ao processar o ER {codigo_er}.")
            log(f"Tipo: {type(erro).__name__}")
            log(f"Detalhes: {erro}")

            captura = (
                PASTA_PROJETO
                / f"erro_venda_direta_{codigo_er}.png"
            )

            try:
                page.screenshot(
                    path=str(captura),
                    full_page=True,
                )
                log(f"Captura salva em: {captura}")

            except Exception:
                pass

            # Tenta recuperar o estado da página para não travar
            # os ERs seguintes.
            fechar_modal_exportacao(page)

    log("Venda Direta - Monitoramento de Base concluído.")


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def executar_etapas(page: Page) -> str:
    etapas_pedidas = [
        nome.strip()
        for nome in os.getenv("ETAPAS", "").lower().split(",")
        if nome.strip()
    ]

    if etapas_pedidas:
        mapa_etapas = {
            "servicos_em_loja": baixar_servicos_em_loja,
            "loja_digital": baixar_loja_digital,
            "treinamentos_forca_vendas": baixar_treinamentos_forca_vendas,
            "treinamentos_iaf_ciclo": baixar_treinamentos_iaf_ciclo,
            "id_cliente": baixar_id_cliente,
            "acao_de_fluxo": baixar_acao_de_fluxo,
            "programa_fidelidade": baixar_programa_fidelidade,
            "canal_loja": baixar_canal_loja,
            "venda_direta": baixar_venda_direta_monitoramento_base,
        }

        desconhecidas = [
            nome for nome in etapas_pedidas if nome not in mapa_etapas
        ]

        if desconhecidas:
            raise ValueError(f"ETAPAS inválidas: {desconhecidas}")

        falhas = []

        for nome in etapas_pedidas:
            try:
                mapa_etapas[nome](page)
            except Exception as erro:
                log(f"FALHA na etapa {nome}: {erro}")
                falhas.append(nome)

                try:
                    page.screenshot(
                        path=str(PASTA_PROJETO / f"erro_{nome}.png"),
                        full_page=True,
                    )
                except Exception:
                    pass

        if falhas:
            raise RuntimeError(
                "Etapas com falha: " + ", ".join(falhas)
            )

        return "etapas"

    fidelidade_e_canal_loja = ETAPA_AUTOMACAO in {
        "fidelidade_canal_loja",
        "fidelidade-canal-loja",
        "fidelidade canal loja",
        "programa_fidelidade_canal_loja",
    }

    if fidelidade_e_canal_loja:
        log(
            "MODO DE TESTE: executando Programa Fidelidade "
            "e Canal Loja."
        )
        baixar_programa_fidelidade(page)
        baixar_canal_loja(page)
        return "fidelidade_canal_loja"

    if ETAPA_AUTOMACAO in {
        "loja_digital_id_cliente",
        "loja-digital-id-cliente",
    }:
        log(
            "MODO DE TESTE: executando Loja Digital "
            "e ID Cliente."
        )
        baixar_loja_digital(page)
        baixar_id_cliente(page)
        return "loja_digital_id_cliente"

    if ETAPA_AUTOMACAO in {
        "acao_de_fluxo",
        "acao-de-fluxo",
    }:
        log("MODO DE TESTE: executando somente Ação de Fluxo.")
        baixar_acao_de_fluxo(page)
        return "acao_de_fluxo"

    if ETAPA_AUTOMACAO in {
        "treinamentos",
        "treinamentos_forca_vendas",
    }:
        log(
            "MODO DE TESTE: executando somente Treinamentos "
            "IAF Força de Vendas."
        )
        baixar_treinamentos_forca_vendas(page)
        return "treinamentos_forca_vendas"

    somente_canal_loja = ETAPA_AUTOMACAO in {
        "canal_loja",
        "canal-loja",
        "canal loja",
    }

    if somente_canal_loja:
        log("MODO DE TESTE: executando somente Canal Loja.")
        baixar_canal_loja(page)
        return "canal_loja"

    somente_venda_direta = ETAPA_AUTOMACAO in {
        "venda_direta",
        "venda-direta",
        "venda direta",
        "monitoramento_base",
    }

    if somente_venda_direta:
        log(
            "MODO DE TESTE: executando somente "
            "Venda Direta - Monitoramento de Base."
        )
        baixar_venda_direta_monitoramento_base(page)
        return "venda_direta"

    if ETAPA_AUTOMACAO not in {
        "",
        "completa",
        "completo",
        "todas",
    }:
        raise ValueError(
            "ETAPA_AUTOMACAO inválida: "
            f"{ETAPA_AUTOMACAO}"
        )

    baixar_servicos_em_loja(page)
    baixar_loja_digital(page)
    baixar_treinamentos_forca_vendas(page)
    baixar_treinamentos_iaf_ciclo(page)
    baixar_id_cliente(page)
    baixar_acao_de_fluxo(page)
    baixar_programa_fidelidade(page)
    baixar_canal_loja(page)
    baixar_venda_direta_monitoramento_base(page)

    return "completa"


def executar():
    validar_configuracoes()

    log("Iniciando a automação de teste.")
    log(f"Downloads: {PASTA_DOWNLOADS}")

    chrome = localizar_chrome()

    log(f"Chrome encontrado: {chrome}")

    comando_chrome = [
        chrome,
        f"--remote-debugging-port={PORTA_DEBUG}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={PASTA_PERFIL}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        "--new-window",
        URL_SITE,
    ]

    log("Abrindo o Google Chrome...")

    processo_chrome = subprocess.Popen(
        comando_chrome
    )

    try:
        websocket = obter_websocket_chrome()

        with sync_playwright() as playwright:
            log("Conectando o Playwright ao Chrome...")

            navegador = playwright.chromium.connect_over_cdp(
                websocket,
                timeout=30_000,
            )

            if not navegador.contexts:
                raise RuntimeError(
                    "Nenhum contexto encontrado no Chrome."
                )

            contexto = navegador.contexts[0]

            contexto.set_default_timeout(
                TIMEOUT_NORMAL
            )

            page = escolher_pagina(contexto)
            page.bring_to_front()

            try:
                esperar_carregamento_inicial(page)
                fazer_login(page)

                clicar_se_aparecer(
                    page,
                    page.get_by_role(
                        "button",
                        name="Agora não",
                    ),
                    timeout=10_000,
                )

                modo_execucao = executar_etapas(page)

                log("======================================")

                if modo_execucao == "fidelidade_canal_loja":
                    log(
                        "TESTE DE FIDELIDADE E CANAL LOJA FINALIZADO."
                    )
                    log("As seis planilhas foram baixadas.")
                elif modo_execucao == "canal_loja":
                    log("TESTE DO CANAL LOJA FINALIZADO.")
                    log("As quatro planilhas foram baixadas.")
                elif modo_execucao == "venda_direta":
                    log(
                        "TESTE DE VENDA DIRETA "
                        "(MONITORAMENTO DE BASE) FINALIZADO."
                    )
                    log("As catorze planilhas foram baixadas.")
                else:
                    log("TESTE FINALIZADO COM SUCESSO.")
                    log("A automação completa foi executada.")

                log("======================================")

            except Exception as erro:
                log("A automação encontrou um erro.")
                log(f"Tipo: {type(erro).__name__}")
                log(f"Detalhes: {erro}")

                captura = (
                    PASTA_PROJETO
                    / "erro_automacao.png"
                )

                try:
                    page.screenshot(
                        path=str(captura),
                        full_page=True,
                    )

                    log(f"Captura salva em: {captura}")

                except Exception:
                    pass

                raise

            finally:
                try:
                    navegador.close()
                except Exception:
                    pass

    finally:
        if processo_chrome.poll() is None:
            log("Encerrando o Google Chrome...")

            processo_chrome.terminate()

            try:
                processo_chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:
                subprocess.run(
                    [
                        "taskkill",
                        "/PID",
                        str(processo_chrome.pid),
                        "/T",
                        "/F",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )

        log("Google Chrome encerrado.")


def executar_no_servidor() -> list[Path]:
    """Executa no Chromium do Playwright, sem Chrome/desktop do Windows."""
    validar_configuracoes()

    arquivos_antes = {
        arquivo.resolve()
        for arquivo in PASTA_DOWNLOADS.glob("*")
        if arquivo.is_file()
    }

    log("Iniciando automação no modo servidor.")
    log(f"Downloads: {PASTA_DOWNLOADS}")

    with sync_playwright() as playwright:
        contexto = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PASTA_PERFIL),
            headless=True,
            accept_downloads=True,
            viewport={"width": 1920, "height": 1080},
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        contexto.set_default_timeout(TIMEOUT_NORMAL)
        page = contexto.pages[0] if contexto.pages else contexto.new_page()

        try:
            page.goto(
                URL_SITE,
                wait_until="domcontentloaded",
                timeout=TIMEOUT_NORMAL,
            )
            esperar_carregamento_inicial(page)
            fazer_login(page)

            clicar_se_aparecer(
                page,
                page.get_by_role("button", name="Agora não"),
                timeout=10_000,
            )

            executar_etapas(page)

        except Exception:
            captura = PASTA_PROJETO / "erro_automacao.png"
            try:
                page.screenshot(path=str(captura), full_page=True)
                log(f"Captura salva em: {captura}")
            except Exception:
                pass
            raise
        finally:
            contexto.close()

    arquivos_depois = {
        arquivo.resolve()
        for arquivo in PASTA_DOWNLOADS.glob("*")
        if arquivo.is_file()
    }
    novos_arquivos = sorted(
        arquivos_depois - arquivos_antes,
        key=lambda arquivo: arquivo.name,
    )

    if not novos_arquivos:
        raise RuntimeError("A execução terminou sem gerar arquivos.")

    log(f"Execução concluída com {len(novos_arquivos)} arquivo(s).")
    return novos_arquivos


if __name__ == "__main__":
    try:
        executar()

    except KeyboardInterrupt:
        print(
            "\nAutomação interrompida pelo usuário."
        )
