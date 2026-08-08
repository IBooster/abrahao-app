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


def _pasta_padrao() -> str:
    """Pasta das planilhas.

    Em producao vem de PASTA_PLANILHAS. Localmente, cai na pasta do OneDrive
    onde os arquivos ja estao, para o sistema rodar sem configuracao.
    """
    do_ambiente = os.environ.get("PASTA_PLANILHAS")
    if do_ambiente:
        return do_ambiente
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


def carregar() -> Config:
    return Config(
        pasta_planilhas=_pasta_padrao(),
        usuario=os.environ.get("APP_USUARIO", ""),
        senha=os.environ.get("APP_SENHA", ""),
        chave_sessao=os.environ.get("APP_CHAVE_SESSAO") or secrets.token_hex(32),
        porta=int(os.environ.get("PORT", "8000")),
        provedor_llm=os.environ.get("LLM_PROVEDOR", "auto"),
        ambiente=os.environ.get("AMBIENTE", "local"),
    )


CONFIG = carregar()
