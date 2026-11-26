import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

# Impede conflito com o Inspector iniciado anteriormente pelo PowerShell.
os.environ.pop("PWDEBUG", None)

from playwright.sync_api import sync_playwright


URL_CANAL_LOJA = (
    "https://extranet.grupoboticario.com.br/"
    "mfe/gi/store-view/performance-v2"
)

# Porta exclusiva para o mapeamento.
PORTA_DEBUG = 9333

PASTA_PROJETO = Path(__file__).resolve().parent
PASTA_PERFIL = PASTA_PROJETO / "perfil_chrome_mapeamento"


def localizar_chrome():
    caminhos = [
        shutil.which("chrome.exe"),
        Path(
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        ),
        Path(
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ),
    ]

    for caminho in caminhos:
        if caminho and Path(caminho).exists():
            return str(caminho)

    raise FileNotFoundError(
        "Google Chrome não foi encontrado."
    )


def obter_websocket():
    endereco = (
        f"http://127.0.0.1:{PORTA_DEBUG}/json/version"
    )

    opener = build_opener(
        ProxyHandler({})
    )

    for tentativa in range(1, 61):
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
                print(
                    "[OK] Chrome disponível para o mapeamento."
                )
                return websocket

        except Exception:
            print(
                f"[AGUARDANDO] Chrome: {tentativa}/60"
            )
            time.sleep(1)

    raise TimeoutError(
        "Não foi possível conectar ao Chrome "
        f"pela porta {PORTA_DEBUG}."
    )


def escolher_pagina(contexto):
    for pagina in reversed(contexto.pages):
        if pagina.url not in ("", "about:blank"):
            return pagina

    return contexto.new_page()


def executar():
    # Opcional: python mapeamento.py "https://extranet..../pagina-alvo"
    # Sem argumento, mantem o comportamento de sempre (Canal Loja).
    url_alvo = sys.argv[1] if len(sys.argv) > 1 else URL_CANAL_LOJA

    chrome = localizar_chrome()

    comando = [
        chrome,
        f"--remote-debugging-port={PORTA_DEBUG}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={PASTA_PERFIL}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        "--new-window",
        url_alvo,
    ]

    print("[INICIANDO] Abrindo o Google Chrome...")

    processo_chrome = subprocess.Popen(comando)

    websocket = obter_websocket()

    if processo_chrome.poll() is not None:
        print(
            "[AVISO] O processo inicial do Chrome foi encerrado, "
            "mas a interface de depuração está disponível."
        )

    with sync_playwright() as playwright:
        print(
            "[CONECTANDO] Playwright conectado ao Chrome..."
        )

        navegador = playwright.chromium.connect_over_cdp(
            websocket,
            timeout=60_000,
        )

        if not navegador.contexts:
            raise RuntimeError(
                "Nenhum contexto foi encontrado no Chrome."
            )

        contexto = navegador.contexts[0]
        contexto.set_default_timeout(60_000)

        page = escolher_pagina(contexto)
        page.bring_to_front()

        if url_alvo not in page.url:
            print(f"[NAVEGANDO] Abrindo {url_alvo}...")

            page.goto(
                url_alvo,
                wait_until="domcontentloaded",
                timeout=120_000,
            )

        print()
        print("==========================================")
        print("MAPEAMENTO DO CANAL LOJA INICIADO")
        print("==========================================")
        print("1. Faça login na conta correta, se necessário.")
        print("2. No Playwright Inspector, clique em Record.")
        print("3. Selecione os filtros do Canal Loja.")
        print("4. Abra a área de exportação.")
        print("5. Copie o código exibido no Inspector.")
        print("6. Não feche o PowerShell durante o processo.")
        print("==========================================")
        print()

        # Abre o Inspector somente depois da conexão com o Chrome.
        page.pause()

        input(
            "Mapeamento encerrado. Pressione ENTER para finalizar..."
        )


if __name__ == "__main__":
    executar()