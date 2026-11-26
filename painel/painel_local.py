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
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAINEL = Path(__file__).resolve().parent
PROJETO = PAINEL.parent

ONEDRIVE = (
    Path(os.environ["OneDriveCommercial"])
    / "dashboards" / "Teste Python" / "automacao"
    if os.environ.get("OneDriveCommercial")
    else Path(
        r"C:\Users\felipe.jesus\OneDrive - Maria Selma Souza Alves "
        r"& Cia Ltda\dashboards\Teste Python\automacao"
    )
)

PORTA = int(os.environ.get("PAINEL_PORTA", "8765"))
TOKEN = secrets.token_urlsafe(16)
PASTA_LOGS = PAINEL / "logs"

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
    "treinamentos_forca_vendas": (
        "Treinamentos IAF, Força de Vendas", "etapa", None, None, "extranet",
    ),
    "treinamentos_iaf_ciclo": (
        "Treinamentos IAF por ciclo", "etapa", None, None, "extranet",
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

PASTAS_ABRIR = {
    "dados_brutos": ONEDRIVE / "dados_brutos",
    "dados_brutos_periodos": ONEDRIVE / "dados_brutos periodos",
    "iaf_vd": ONEDRIVE / "iaf vd",
    "iaf_vd_ciclos": ONEDRIVE / "iaf vd ciclos",
    "iaf_vd_periodos": ONEDRIVE / "iaf vd periodos",
    "medallia_periodos": ONEDRIVE / "medallia periodos",
    "logs": PASTA_LOGS,
}

PADRAO_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")

TRAVA = threading.Lock()
estado: dict = {
    "rodando": False,
    "status": {},
    "linhas": [],
    "inicio": None,
    "fim": None,
    "resultado": None,
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

def montar_jobs(ids: list[str], config: dict) -> list[dict]:
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
    base.pop("HUB_SAIDA", None)
    base.pop("ETAPAS", None)

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

    try:
        for indice, job in enumerate(jobs, start=1):
            if parar.is_set():
                for i in job["ids"]:
                    estado["status"][i] = "cancelado"
                continue

            registrar("")
            registrar(f"===== [{indice}/{len(jobs)}] {job['nome']} =====")
            for i in job["ids"]:
                estado["status"][i] = "rodando"

            try:
                codigo = rodar_job(job)
            except Exception as erro:
                registrar(f"Não foi possível iniciar: {erro}")
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
    finally:
        with TRAVA:
            estado["rodando"] = False
            estado["fim"] = datetime.now().isoformat(timespec="seconds")
            valores = list(estado["status"].values())
            estado["resultado"] = (
                "cancelado" if parar.is_set()
                else "ok" if all(v == "ok" for v in valores)
                else "erro"
            )
            estado["arquivo_log"] = None
        arquivo.close()


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

    with TRAVA:
        if estado["rodando"]:
            return "Já existe uma execução em andamento."
        parar.clear()
        estado.update({
            "rodando": True,
            "status": {i: "aguardando" for i in ids},
            "linhas": [],
            "inicio": datetime.now().isoformat(timespec="seconds"),
            "fim": None,
            "resultado": None,
        })

    threading.Thread(
        target=executar, args=(ids, config), daemon=True
    ).start()
    return None


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
    env_proj = ler_env(PROJETO / ".env")
    env_one = ler_env(ONEDRIVE / ".env")

    def tem_extranet(env: dict) -> bool:
        usuario = (
            env.get("EXTRANET_USUARIO") or env.get("USUARIO")
            or env.get("LOGIN") or os.environ.get("EXTRANET_USUARIO")
        )
        senha = (
            env.get("EXTRANET_SENHA") or env.get("SENHA")
            or env.get("PASSWORD") or os.environ.get("EXTRANET_SENHA")
        )
        return bool(usuario and senha)

    return {
        "extranet": tem_extranet(env_proj),
        "extranet_onedrive": tem_extranet(env_one),
        "medallia": bool(
            os.environ.get("BOTI_USUARIO") and os.environ.get("BOTI_SENHA")
        ),
        "scripts_ok": all(
            (
                (PROJETO / "teste_playwright.py").exists()
                if script is None
                else (pasta / script).exists()
            )
            for _, _, script, pasta, _ in CATALOGO.values()
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
                }
            self._json(resposta)
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

    threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
