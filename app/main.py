# -*- coding: utf-8 -*-
"""Aplicacao web.

Fase 2: somente leitura. Nao existe rota que escreva em planilha, e o unico
modulo capaz de abrir arquivo o faz com read_only=True.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Cookie, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import arquivos as arq
from .chat.router import Roteador
from .config import CONFIG
from .domain.loader import Repositorio
from .llm.provedores import obter_provedor
from .queries import engine as E

RAIZ = Path(__file__).resolve().parent
ESTATICOS = RAIZ / "web" / "static"
PAGINAS = RAIZ / "web" / "paginas"

app = FastAPI(title="Financeiro - assistente de consulta", docs_url=None, redoc_url=None)

if ESTATICOS.exists():
    app.mount("/static", StaticFiles(directory=str(ESTATICOS)), name="static")

repositorio = Repositorio(CONFIG.pasta_planilhas)
roteador = Roteador(repositorio, obter_provedor(E.CATALOGO))


# ---------------------------------------------------------------------------
# Sessao
# ---------------------------------------------------------------------------

NOME_COOKIE = "sessao"


def _assinar(valor: str) -> str:
    assinatura = hmac.new(
        CONFIG.chave_sessao.encode(), valor.encode(), hashlib.sha256
    ).hexdigest()
    return f"{valor}.{assinatura}"


def _validar(cookie: Optional[str]) -> Optional[str]:
    if not cookie or "." not in cookie:
        return None
    valor, _, assinatura = cookie.rpartition(".")
    esperado = hmac.new(
        CONFIG.chave_sessao.encode(), valor.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(assinatura, esperado):
        return None
    return valor


def _autenticado(sessao: Optional[str]) -> Optional[str]:
    if not CONFIG.autenticacao_configurada:
        # Sem credencial configurada a aplicacao roda aberta em ambiente local,
        # para nao travar o desenvolvimento. Em producao, APP_USUARIO e
        # APP_SENHA sao obrigatorios - ver checagem no startup.
        return "local"
    return _validar(sessao)


def _exigir(sessao: Optional[str]) -> str:
    usuario = _autenticado(sessao)
    if not usuario:
        raise HTTPException(status_code=401, detail="Sessao expirada.")
    return usuario


@asynccontextmanager
async def _ciclo_de_vida(_: FastAPI):
    if CONFIG.ambiente == "producao" and not CONFIG.autenticacao_configurada:
        raise RuntimeError(
            "AMBIENTE=producao exige APP_USUARIO e APP_SENHA definidos."
        )
    yield


app.router.lifespan_context = _ciclo_de_vida


# ---------------------------------------------------------------------------
# Paginas
# ---------------------------------------------------------------------------


def _pagina(nome: str) -> str:
    caminho = PAGINAS / nome
    if not caminho.exists():
        return "<h1>Pagina nao encontrada</h1>"
    return caminho.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def raiz(sessao: Optional[str] = Cookie(default=None)):
    if not _autenticado(sessao):
        return RedirectResponse("/entrar", status_code=303)
    return HTMLResponse(_pagina("chat.html"))


@app.get("/entrar", response_class=HTMLResponse)
def entrar(sessao: Optional[str] = Cookie(default=None)):
    if _autenticado(sessao):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(_pagina("entrar.html"))


@app.post("/entrar")
def autenticar(
    response: Response,
    usuario: str = Form(...),
    senha: str = Form(...),
):
    ok_usuario = hmac.compare_digest(usuario.strip(), CONFIG.usuario)
    ok_senha = hmac.compare_digest(senha, CONFIG.senha)
    if not (ok_usuario and ok_senha):
        pagina = _pagina("entrar.html").replace(
            "<!--ERRO-->",
            '<p class="erro">Usuario ou senha nao conferem. Tente de novo.</p>',
        )
        return HTMLResponse(pagina, status_code=401)

    token = _assinar(f"{usuario.strip()}:{secrets.token_hex(8)}")
    resposta = RedirectResponse("/", status_code=303)
    resposta.set_cookie(
        NOME_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=CONFIG.ambiente == "producao",
        max_age=60 * 60 * 12,
    )
    return resposta


@app.post("/sair")
def sair():
    resposta = RedirectResponse("/entrar", status_code=303)
    resposta.delete_cookie(NOME_COOKIE)
    return resposta


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class Pergunta(BaseModel):
    texto: str


@app.post("/api/perguntar")
def perguntar(
    pergunta: Pergunta, sessao: Optional[str] = Cookie(default=None)
):
    _exigir(sessao)
    resposta = roteador.responder(pergunta.texto)
    return JSONResponse(resposta.__dict__)


@app.get("/api/estado")
def estado(sessao: Optional[str] = Cookie(default=None)):
    _exigir(sessao)
    return JSONResponse(roteador.estado())


@app.get("/api/sugestoes")
def sugestoes(sessao: Optional[str] = Cookie(default=None)):
    _exigir(sessao)
    return JSONResponse({"sugestoes": roteador.sugestoes()})


@app.post("/api/recarregar")
def recarregar(sessao: Optional[str] = Cookie(default=None)):
    """Rele as planilhas do disco. Nao escreve nada."""
    _exigir(sessao)
    repositorio.recarregar()
    return JSONResponse(roteador.estado())


# ---------------------------------------------------------------------------
# Planilhas
#
# O disco do Railway e efemero e nao ha OneDrive la, entao os arquivos chegam
# por aqui. Substituir arquivo inteiro nao e o mesmo que alterar planilha: o
# conteudo nunca e tocado pelo sistema. Ver app/arquivos.py.
# ---------------------------------------------------------------------------


@app.get("/planilhas", response_class=HTMLResponse)
def pagina_planilhas(sessao: Optional[str] = Cookie(default=None)):
    if not _autenticado(sessao):
        return RedirectResponse("/entrar", status_code=303)
    return HTMLResponse(_pagina("planilhas.html"))


@app.get("/api/planilhas")
def listar_planilhas(sessao: Optional[str] = Cookie(default=None)):
    _exigir(sessao)
    return JSONResponse(
        {
            "pasta": CONFIG.pasta_planilhas,
            "arquivos": [
                {
                    "nome": e.nome,
                    "rotulo": e.rotulo,
                    "descricao": e.descricao,
                    "presente": e.presente,
                    "tamanho": e.tamanho_legivel,
                    "atualizado_em": e.atualizado_em,
                }
                for e in arq.situacao(CONFIG.pasta_planilhas)
            ],
            "faltando": arq.faltando(CONFIG.pasta_planilhas),
            "historico": arq.historico(CONFIG.pasta_planilhas),
        }
    )


@app.post("/api/planilhas")
async def enviar_planilha(
    arquivo: UploadFile = File(...),
    sessao: Optional[str] = Cookie(default=None),
):
    usuario = _exigir(sessao)
    conteudo = await arquivo.read()
    try:
        recebido = arq.receber(
            CONFIG.pasta_planilhas, arquivo.filename or "", conteudo, usuario
        )
    except arq.ArquivoRecusado as erro:
        return JSONResponse({"ok": False, "erro": str(erro)}, status_code=400)
    except OSError as erro:
        return JSONResponse(
            {
                "ok": False,
                "erro": (
                    f"Não consegui gravar na pasta {CONFIG.pasta_planilhas}: "
                    f"{erro.strerror or erro}. No Railway, confira se o volume "
                    f"está montado e se PASTA_PLANILHAS aponta para ele."
                ),
            },
            status_code=500,
        )

    # Releitura e conveniencia: adianta a proxima consulta. Se falhar - e ela
    # falha enquanto os outros arquivos nao chegaram -, o envio continua
    # valido. O cache invalida por mtime de qualquer forma.
    pendentes = arq.faltando(CONFIG.pasta_planilhas)
    if not pendentes:
        try:
            repositorio.recarregar()
        except Exception:
            pass

    return JSONResponse(
        {
            "ok": True,
            "arquivo": recebido.nome,
            "rotulo": recebido.rotulo,
            "abas": recebido.abas,
            "substituiu": recebido.substituiu,
            "backup": recebido.backup,
            "faltando": pendentes,
        }
    )


@app.get("/saude")
def saude():
    """Usada pelo Railway para saber se o servico subiu."""
    return {
        "ok": True,
        "planilhas_faltando": len(arq.faltando(CONFIG.pasta_planilhas)),
    }
