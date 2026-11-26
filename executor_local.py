import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PASTA_PROJETO = Path(
    r"C:\Users\Admin\Downloads\automacao_extranet\automacao_extranet"
)
PYTHON_VENV = PASTA_PROJETO / "venv" / "Scripts" / "python.exe"
SCRIPT_AUTOMACAO = PASTA_PROJETO / "teste_playwright.py"
ARQUIVO_LOG = PASTA_PROJETO / "automacao_n8n.log"

processo_atual = None
servidor = None
bloqueio = threading.Lock()
estado_atual = "aguardando"
codigo_saida_atual = None
mensagem_atual = "Aguardando o disparo da automação."
resultado_consultado = threading.Event()


def definir_estado(estado, mensagem, codigo_saida=None):
    global estado_atual
    global mensagem_atual
    global codigo_saida_atual

    with bloqueio:
        estado_atual = estado
        mensagem_atual = mensagem
        codigo_saida_atual = codigo_saida


def ultima_linha_log():
    if not ARQUIVO_LOG.exists():
        return ""

    try:
        linhas = ARQUIVO_LOG.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()

        for linha in reversed(linhas):
            linha = linha.strip()
            if linha:
                return linha

    except OSError:
        return ""

    return ""


def encerrar_apos_resultado():
    # Encerra logo após o n8n consultar o resultado. Se a consulta não
    # chegar, fecha em 30 segundos para não deixar o .bat aberto.
    resultado_consultado.wait(timeout=30)
    time.sleep(2)

    if servidor is not None:
        servidor.shutdown()


def executar_automacao():
    global processo_atual

    try:
        with ARQUIVO_LOG.open(
            "a",
            encoding="utf-8",
        ) as log:
            horario = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            log.write(
                "\n"
                f"[{horario}] ===== NOVA EXECUÇÃO =====\n"
            )
            log.flush()

            processo = subprocess.Popen(
                [
                    str(PYTHON_VENV),
                    "-u",
                    str(SCRIPT_AUTOMACAO),
                ],
                cwd=str(PASTA_PROJETO),
                stdout=log,
                stderr=subprocess.STDOUT,
                # O Playwright grava tudo em automacao_n8n.log. Não abre
                # outro console que possa ficar aguardando ENTER ao terminar.
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            with bloqueio:
                processo_atual = processo

            definir_estado(
                "executando",
                "Playwright iniciado. Aguardando progresso.",
            )

            codigo_saida = processo.wait()

            log.write(
                "\n"
                f"Automação encerrada com código {codigo_saida}.\n"
            )
            log.flush()

            if codigo_saida == 0:
                definir_estado(
                    "concluido",
                    "Automação concluída com sucesso.",
                    codigo_saida,
                )
            else:
                definir_estado(
                    "erro",
                    (
                        "A automação encontrou um erro "
                        f"e encerrou com código {codigo_saida}. "
                        "Consulte automacao_n8n.log."
                    ),
                    codigo_saida,
                )

    except Exception as erro:
        definir_estado(
            "erro",
            (
                f"Falha no executor: {type(erro).__name__}: "
                f"{erro}"
            ),
            -1,
        )

    finally:
        with bloqueio:
            processo_atual = None

        threading.Thread(
            target=encerrar_apos_resultado,
            daemon=True,
        ).start()


class ExecutorHandler(BaseHTTPRequestHandler):

    def responder(self, status, mensagem):
        conteudo = mensagem.encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(conteudo)),
        )
        self.end_headers()
        self.wfile.write(conteudo)

    def do_POST(self):
        global processo_atual
        global estado_atual
        global mensagem_atual
        global codigo_saida_atual

        if self.path != "/executar":
            self.responder(
                404,
                "Rota não encontrada.",
            )
            return

        if not PYTHON_VENV.exists():
            self.responder(
                500,
                f"Python não encontrado: {PYTHON_VENV}",
            )
            return

        if not SCRIPT_AUTOMACAO.exists():
            self.responder(
                500,
                f"Script não encontrado: {SCRIPT_AUTOMACAO}",
            )
            return

        with bloqueio:
            if (
                estado_atual in {"iniciando", "executando"}
                or (
                    processo_atual is not None
                    and processo_atual.poll() is None
                )
            ):
                self.responder(
                    409,
                    "A automação já está em execução.",
                )
                return

            if estado_atual in {"concluido", "erro"}:
                self.responder(
                    409,
                    "O resultado anterior ainda está sendo finalizado.",
                )
                return

            resultado_consultado.clear()
            estado_atual = "iniciando"
            mensagem_atual = "Preparando a automação."
            codigo_saida_atual = None

            thread = threading.Thread(
                target=executar_automacao,
                daemon=True,
            )
            thread.start()

        self.responder(
            202,
            "iniciado|Automação iniciada com sucesso.",
        )

    def do_GET(self):
        if self.path != "/status":
            self.responder(
                404,
                "Rota não encontrada.",
            )
            return

        with bloqueio:
            estado = estado_atual
            mensagem = mensagem_atual

        if estado in {"iniciando", "executando"}:
            progresso = ultima_linha_log() or mensagem
            self.responder(
                200,
                f"executando|{progresso}",
            )
            return

        if estado == "concluido":
            self.responder(
                200,
                f"concluido|{mensagem}",
            )
            resultado_consultado.set()
            return

        if estado == "erro":
            self.responder(
                200,
                f"erro|{mensagem}",
            )
            resultado_consultado.set()
            return

        self.responder(
            200,
            f"aguardando|{mensagem}",
        )

    def log_message(self, formato, *args):
        return


if __name__ == "__main__":
    servidor = ThreadingHTTPServer(
        ("0.0.0.0", 8765),
        ExecutorHandler,
    )

    print("Executor local iniciado.")
    print("Endereço: http://localhost:8765")
    print(
        "A janela fechará automaticamente "
        "quando a automação terminar."
    )

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nExecutor encerrado.")
    finally:
        servidor.server_close()
