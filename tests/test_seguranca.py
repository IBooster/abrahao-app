# -*- coding: utf-8 -*-
"""Testes de seguranca da Fase 2.

O compromisso da Fase 2 e que o sistema NAO escreve em planilha. Isso nao pode
depender de disciplina de quem programa; precisa falhar o teste se alguem
introduzir um caminho de escrita.

Rodar:  python -m pytest tests -v
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

APP = RAIZ / "app"

# Metodos que gravam arquivo independentemente de quem os chame.
# 'save' cobre Workbook.save, que e o risco real neste projeto.
METODOS_SEMPRE_PROIBIDOS = {"save", "truncate", "writelines"}

# Metodos de filesystem que so contam quando chamados sobre os modulos abaixo.
# Sem esse recorte, str.replace e list.remove viram falso positivo.
METODOS_DE_FILESYSTEM = {
    "remove",
    "unlink",
    "rmtree",
    "rename",
    "replace",
    "mkdir",
    "makedirs",
    "copy",
    "copy2",
    "copyfile",
    "move",
}
MODULOS_DE_FILESYSTEM = {"os", "shutil", "pathlib", "Path"}

MODOS_DE_ESCRITA = ("w", "a", "x", "+")


def _arquivos_python() -> list[Path]:
    return [p for p in APP.rglob("*.py") if "__pycache__" not in str(p)]


def _raiz_do_receptor(no: ast.AST) -> str | None:
    """Nome da base de uma cadeia de atributos: os.path.join -> 'os'."""
    atual = no
    while isinstance(atual, ast.Attribute):
        atual = atual.value
    if isinstance(atual, ast.Name):
        return atual.id
    return None


def test_nenhuma_chamada_de_escrita_em_arquivo():
    """Nenhum modulo do app chama metodo capaz de gravar ou apagar arquivo."""
    achados = []
    for caminho in _arquivos_python():
        arvore = ast.parse(caminho.read_text(encoding="utf-8"), filename=str(caminho))
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call) or not isinstance(no.func, ast.Attribute):
                continue
            metodo = no.func.attr
            local = f"{caminho.relative_to(RAIZ)}:{no.lineno}"

            if metodo in METODOS_SEMPRE_PROIBIDOS:
                achados.append(f"{local} -> {metodo}()")
                continue

            if metodo in METODOS_DE_FILESYSTEM:
                raiz = _raiz_do_receptor(no.func.value)
                if raiz in MODULOS_DE_FILESYSTEM:
                    achados.append(f"{local} -> {raiz}.{metodo}()")

    assert not achados, (
        "Chamada de escrita encontrada no pacote app. A Fase 2 e somente "
        "leitura:\n  " + "\n  ".join(achados)
    )


def test_nenhum_open_em_modo_de_escrita():
    """Nenhum open() do app usa modo de escrita."""
    achados = []
    for caminho in _arquivos_python():
        arvore = ast.parse(caminho.read_text(encoding="utf-8"), filename=str(caminho))
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue
            alvo = no.func
            nome = alvo.id if isinstance(alvo, ast.Name) else getattr(alvo, "attr", None)
            if nome not in ("open", "write_text", "write_bytes"):
                continue
            if nome in ("write_text", "write_bytes"):
                achados.append(f"{caminho.relative_to(RAIZ)}:{no.lineno} -> {nome}()")
                continue
            if len(no.args) >= 2 and isinstance(no.args[1], ast.Constant):
                modo = str(no.args[1].value)
                if any(m in modo for m in MODOS_DE_ESCRITA):
                    achados.append(
                        f"{caminho.relative_to(RAIZ)}:{no.lineno} -> open(..., {modo!r})"
                    )
    assert not achados, "open() em modo de escrita:\n  " + "\n  ".join(achados)


def test_workbooks_abertos_somente_leitura():
    """Toda chamada a load_workbook passa read_only=True."""
    from app.domain import loader

    fonte = Path(loader.__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    chamadas = [
        no
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call)
        and getattr(no.func, "attr", None) == "load_workbook"
    ]
    assert chamadas, "Esperava encontrar load_workbook no loader."
    for chamada in chamadas:
        argumentos = {kw.arg: kw.value for kw in chamada.keywords}
        assert "read_only" in argumentos, (
            f"load_workbook na linha {chamada.lineno} sem read_only."
        )
        valor = argumentos["read_only"]
        assert isinstance(valor, ast.Constant) and valor.value is True, (
            f"load_workbook na linha {chamada.lineno} com read_only diferente de True."
        )


def test_nenhuma_rota_de_escrita_em_planilha():
    """As rotas POST existentes nao alteram planilha."""
    from app import main

    rotas_post = {
        rota.path
        for rota in main.app.routes
        if "POST" in getattr(rota, "methods", set())
    }
    permitidas = {"/entrar", "/sair", "/api/perguntar", "/api/recarregar"}
    inesperadas = rotas_post - permitidas
    assert not inesperadas, f"Rota POST nao prevista na Fase 2: {inesperadas}"


def test_schema_declara_modo_somente_leitura():
    from app.domain import schema

    assert schema.MODO_SOMENTE_LEITURA is True


def test_nenhuma_operacao_de_escrita_implementada():
    """As operacoes planejadas para a Fase 3 nao existem como funcao."""
    from app.domain import schema
    from app.queries import engine

    for nome in schema.OPERACOES_ESCRITA_PLANEJADAS:
        assert not hasattr(engine, nome), (
            f"A operacao de escrita '{nome}' aparece no motor de consultas. "
            f"Ela pertence a Fase 3 e depende de aprovacao."
        )
        assert nome not in engine.CATALOGO, (
            f"A operacao de escrita '{nome}' esta no catalogo de consultas."
        )


def test_arquivos_nao_mudam_apos_uso():
    """Le, consulta tudo, e confere que nenhum arquivo foi tocado no disco."""
    from app.config import CONFIG
    from app.domain import schema
    from app.domain.loader import carregar
    from app.queries import engine

    base = CONFIG.pasta_planilhas
    if not os.path.isdir(base):
        pytest.skip("Pasta de planilhas nao disponivel neste ambiente.")

    antes = {}
    for arquivo in schema.ARQUIVOS_ESPERADOS:
        caminho = os.path.join(base, arquivo)
        if os.path.exists(caminho):
            info = os.stat(caminho)
            antes[arquivo] = (info.st_mtime_ns, info.st_size)

    indice = carregar(base)
    for nome, consulta in engine.CATALOGO.items():
        parametros = {}
        if "cliente" in consulta.parametros:
            parametros["cliente"] = "BMG"
        if "conta" in consulta.parametros:
            parametros["conta"] = "santander"
        if "mes" in consulta.parametros:
            parametros["mes"] = 7
        engine.executar(indice, nome, parametros)

    for arquivo, esperado in antes.items():
        caminho = os.path.join(base, arquivo)
        info = os.stat(caminho)
        assert (info.st_mtime_ns, info.st_size) == esperado, (
            f"O arquivo {arquivo} mudou depois de consultar. A Fase 2 nao "
            f"pode alterar planilha."
        )
