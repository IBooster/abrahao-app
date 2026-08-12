# -*- coding: utf-8 -*-
"""Configuracao por variavel de ambiente.

Nenhum segredo mora no codigo nem no repositorio. O .env fica fora do git e
o .env.example lista apenas os NOMES das variaveis.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _carregar_env() -> None:
    """Le um .env local, quando existir. No Railway as variaveis ja vem do ambiente."""
    caminho = Path(__file__).resolve().parent.parent / ".env"
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        os.environ.setdefault(chave, valor)


_carregar_env()


@dataclass(frozen=True)
class Config:
    pasta_planilhas: str
    usuario: str
    senha: str
    chave_sessao: str
    porta: int
    provedor_llm: str
    ambiente: str

    @property
    def autenticacao_configurada(self) -> bool:
        return bool(self.usuario and self.senha)


def _no_railway() -> bool:
    """O Railway define estas sozinho. Serve para acertar os padroes la."""
    return any(
        os.environ.get(v)
        for v in ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")
    )


def _pasta_padrao() -> str:
    """Pasta das planilhas.

    PASTA_PLANILHAS manda, quando definida. No Railway o padrao e /data, que
    e onde o volume e montado - sem isso o app gravaria num diretorio efemero
    e as planilhas sumiriam a cada deploy. Localmente cai na pasta do OneDrive.
    """
    do_ambiente = os.environ.get("PASTA_PLANILHAS")
    if do_ambiente:
        return do_ambiente
    if _no_railway():
        return "/data"
    local = (
        Path.home()
        / "OneDrive - Insper - Instituto de Ensino e Pesquisa"
        / "Área de Trabalho"
        / "IBOOSTER"
        / "Abrahão Advogados"
    )
    if local.exists():
        return str(local)
    return str(Path(__file__).resolve().parent.parent / "planilhas")


def _ambiente_padrao() -> str:
    """No Railway, producao por padrao.

    Fecha por seguranca: em servidor publico o app exige login, a menos que
    alguem escreva AMBIENTE=local de proposito.
    """
    do_ambiente = os.environ.get("AMBIENTE")
    if do_ambiente:
        return do_ambiente.strip().lower()
    return "producao" if _no_railway() else "local"


def _chave_de_sessao(pasta: str) -> str:
    """Chave que assina o cookie.

    Se APP_CHAVE_SESSAO nao vier, gera uma e guarda no volume. Sem guardar,
    uma nova seria sorteada a cada reinicio e todo mundo cairia da sessao.
    A gravacao mora em arquivos.py, o modulo que pode escrever.
    """
    do_ambiente = os.environ.get("APP_CHAVE_SESSAO")
    if do_ambiente:
        return do_ambiente
    from .arquivos import chave_de_sessao_persistida

    try:
        return chave_de_sessao_persistida(pasta)
    except OSError:
        # Volume indisponivel: chave de memoria. A sessao cai no reinicio,
        # mas o app sobe.
        return secrets.token_hex(32)


def carregar() -> Config:
    pasta = _pasta_padrao()
    return Config(
        pasta_planilhas=pasta,
        usuario=os.environ.get("APP_USUARIO", ""),
        senha=os.environ.get("APP_SENHA", ""),
        chave_sessao=_chave_de_sessao(pasta),
        porta=int(os.environ.get("PORT", "8000")),
        provedor_llm=os.environ.get("LLM_PROVEDOR", "auto"),
        ambiente=_ambiente_padrao(),
    )


CONFIG = carregar()
