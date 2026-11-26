import json
import os
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

URL_PLATAFORMA_LOGISTICA = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/order-management/logistics-platform-adherence"
)

PORTA_DEBUG = 9225

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

PASTA_DOWNLOADS = Path(
    r"C:\Users\Admin\OneDrive - Maria Selma Souza Alves & Cia Ltda\dashboards\Teste Python\automacao\dados_brutos"
)

TIMEOUT_NORMAL = 45_000
TIMEOUT_RELATORIO = 900_000

# Pausa entre cliques/preenchimentos.
ESPERA_ANTES_ACAO = 2_000

# Tempo para o dashboard terminar de atualizar depois de abrir uma área
# ou trocar de aba.
ESPERA_DASHBOARD = 8_000

# Tempo de cada tentativa de clique antes de usar o fallback.
TIMEOUT_CLIQUE = 8_000

# Plataforma Logística processa a planilha de forma assíncrona: depois de
# pedir a exportação é preciso aguardar o processamento e recarregar a
# página para o link "Salvar dados" ficar disponível no histórico.
ESPERA_PROCESSAMENTO_PLATAFORMA_LOGISTICA = 45_000


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
    nome_original = Path(nome_original).name

    if not nome_original:
        data_atual = datetime.now().strftime("%d-%m-%Y")
        nome_original = f"download-{data_atual}.xlsx"

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

    locator.evaluate("elemento => elemento.click()")


def esperar_botao_exportar(page: Page) -> Locator:
    log("Aguardando o botão Exportar...")

    botao = page.get_by_test_id(
        "button-export"
    )

    botao.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    expect(botao).to_be_enabled(
        timeout=TIMEOUT_NORMAL,
    )

    log("Botão Exportar disponível.")

    return botao


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

    fechar_aviso_notificacoes(
        page,
        timeout=5_000,
    )

    log(f"Área carregada: {nome_area}")


def abrir_aba_por_texto(
    page: Page,
    texto: str,
):
    log(f"Abrindo a aba: {texto}")

    aba = page.get_by_role(
        "tab",
        name=texto,
        exact=True,
    )

    if aba.count() == 0:
        aba = page.get_by_text(
            texto,
            exact=True,
        ).first

    aba.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    clicar_com_fallback(
        page,
        aba,
        texto,
    )

    page.wait_for_timeout(
        ESPERA_DASHBOARD
    )


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
# GESTÃO DE PEDIDOS: PLATAFORMA LOGÍSTICA
# ============================================================

def abrir_painel_exportacao_plataforma_logistica(
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


def marcar_checkbox_plataforma_logistica(page: Page):
    texto = "Visão detalhada da utilização por pedido"

    log(f"Marcando: {texto}")

    texto_opcao = page.get_by_text(
        texto,
        exact=True,
    ).last

    texto_opcao.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

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
    ]

    checkbox = None

    for candidato in seletores:
        if candidato.count() > 0:
            checkbox = candidato.first
            break

    if checkbox is None:
        checkbox = page.get_by_role(
            "checkbox",
            name=texto,
            exact=True,
        )

    checkbox = normalizar_controle_checkbox(checkbox)

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


def solicitar_exportacao_plataforma_logistica(page: Page):
    abrir_painel_exportacao_plataforma_logistica(page)

    esperar_antes(page)
    marcar_checkbox_plataforma_logistica(page)

    botao_exportar_selecao = page.get_by_role(
        "button",
        name="Exportar seleção",
        exact=True,
    ).last

    if botao_exportar_selecao.count() == 0:
        botao_exportar_selecao = page.get_by_test_id(
            "btn-export-modal"
        )

    botao_exportar_selecao.wait_for(
        state="visible",
        timeout=TIMEOUT_NORMAL,
    )

    expect(botao_exportar_selecao).to_be_enabled(
        timeout=TIMEOUT_NORMAL,
    )

    esperar_antes(page)

    log(
        "Solicitando a geração da planilha de "
        "Plataforma Logística..."
    )
    clicar_com_fallback(
        page,
        botao_exportar_selecao,
        "Exportar seleção",
    )


def baixar_plataforma_logistica(page: Page):
    log("========== PLATAFORMA LOGÍSTICA ==========")

    abrir_area_direta(
        page,
        "Gestão de Pedidos - Plataforma Logística",
        URL_PLATAFORMA_LOGISTICA,
    )

    abrir_aba_por_texto(page, "Plataforma Logística")

    solicitar_exportacao_plataforma_logistica(page)

    log(
        "Aguardando o processamento da planilha "
        f"({ESPERA_PROCESSAMENTO_PLATAFORMA_LOGISTICA // 1000}s)..."
    )
    page.wait_for_timeout(
        ESPERA_PROCESSAMENTO_PLATAFORMA_LOGISTICA
    )

    log("Recarregando a página para liberar o download...")
    page.reload(
        wait_until="domcontentloaded",
        timeout=TIMEOUT_NORMAL,
    )

    page.wait_for_timeout(
        ESPERA_DASHBOARD
    )

    fechar_aviso_notificacoes(
        page,
        timeout=5_000,
    )

    abrir_aba_por_texto(page, "Plataforma Logística")

    abrir_painel_exportacao_plataforma_logistica(page)

    botao_salvar = page.get_by_text(
        "Salvar dados",
        exact=True,
    ).first

    botao_salvar.wait_for(
        state="visible",
        timeout=TIMEOUT_RELATORIO,
    )

    esperar_antes(page)

    log("Baixando: PlataformaLogisticaVisaoDetalhada")

    with page.expect_download(
        timeout=TIMEOUT_RELATORIO,
    ) as download_info:
        botao_salvar.click()

    salvar_download(
        download_info.value,
        "PlataformaLogisticaVisaoDetalhada",
    )

    log("Plataforma Logística concluído.")


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def executar():
    validar_configuracoes()

    log("Iniciando a automação de Plataforma Logística.")
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

                baixar_plataforma_logistica(page)

                log("======================================")
                log("PLATAFORMA LOGÍSTICA FINALIZADA COM SUCESSO.")
                log("======================================")

            except Exception as erro:
                log("A automação encontrou um erro.")
                log(f"Tipo: {type(erro).__name__}")
                log(f"Detalhes: {erro}")

                captura = (
                    PASTA_PROJETO
                    / "erro_plataforma_logistica.png"
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


if __name__ == "__main__":
    try:
        executar()

    except KeyboardInterrupt:
        print(
            "\nAutomação interrompida pelo usuário."
        )
