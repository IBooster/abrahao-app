# -*- coding: utf-8 -*-
"""Guarda das planilhas: o unico modulo do sistema que escreve em disco.

Existe porque no Railway o disco do container e efemero e nao ha OneDrive:
alguem precisa colocar os cinco arquivos la. Este modulo recebe um arquivo
enviado pela usuaria e o coloca no lugar.

O que ele NAO faz, e e o ponto:

    Ele nunca altera o conteudo de uma planilha. Nao abre celula, nao muda
    formula, nao acrescenta linha. Ele substitui um arquivo inteiro por outro
    que a usuaria mandou de proposito, e guarda o anterior antes.

A promessa de somente leitura sobre o DADO CONTABIL continua valendo, e o
teste de seguranca agora verifica duas coisas: que nenhum outro modulo escreve,
e que este aqui so escreve nos cinco nomes conhecidos, dentro da pasta
configurada.

Ordem de cada envio, e ela importa:

    1. confere o nome contra a lista de arquivos esperados
    2. abre o que chegou e confere se as abas obrigatorias estao la
    3. so entao guarda copia do anterior
    4. grava em arquivo temporario e troca de uma vez (os.replace e atomico)
    5. registra na auditoria

Se qualquer passo falhar, nada e substituido.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import secrets
import shutil
from dataclasses import dataclass
from typing import Optional

import openpyxl

from .domain import schema as sch

# Um arquivo maior que isso nao e planilha do escritorio, e algo errado.
# O maior hoje (fluxo de caixa) tem 1,4 MB.
LIMITE_BYTES = 25 * 1024 * 1024

ASSINATURA_XLSX = b"PK\x03\x04"


class ArquivoRecusado(Exception):
    """O arquivo enviado nao passou na conferencia. Nada foi substituido."""


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------


@dataclass
class EstadoArquivo:
    nome: str
    rotulo: str
    descricao: str
    presente: bool
    tamanho: Optional[int] = None
    atualizado_em: Optional[str] = None

    @property
    def tamanho_legivel(self) -> str:
        if self.tamanho is None:
            return "-"
        if self.tamanho >= 1024 * 1024:
            return f"{self.tamanho / (1024 * 1024):.1f} MB"
        return f"{self.tamanho / 1024:.0f} KB"


def situacao(base: str) -> list[EstadoArquivo]:
    """Quais dos cinco arquivos ja estao na pasta."""
    estados = []
    for nome, esperado in sch.ARQUIVOS.items():
        caminho = os.path.join(base, nome)
        if os.path.exists(caminho):
            info = os.stat(caminho)
            estados.append(
                EstadoArquivo(
                    nome=nome,
                    rotulo=esperado.rotulo,
                    descricao=esperado.descricao,
                    presente=True,
                    tamanho=info.st_size,
                    atualizado_em=dt.datetime.fromtimestamp(info.st_mtime).strftime(
                        "%d/%m/%Y %H:%M"
                    ),
                )
            )
        else:
            estados.append(
                EstadoArquivo(
                    nome=nome,
                    rotulo=esperado.rotulo,
                    descricao=esperado.descricao,
                    presente=False,
                )
            )
    return estados


def faltando(base: str) -> list[str]:
    return [e.nome for e in situacao(base) if not e.presente]


# ---------------------------------------------------------------------------
# Conferencia
# ---------------------------------------------------------------------------


def _resolver_nome(nome_enviado: str) -> str:
    """Casa o nome do arquivo enviado com um dos cinco esperados.

    Nao aceita caminho: so o nome do arquivo, e so se estiver na lista. Isso
    fecha a porta para gravar fora da pasta.
    """
    limpo = os.path.basename((nome_enviado or "").strip())
    if limpo in sch.ARQUIVOS:
        return limpo
    # Tolera diferenca de caixa, que acontece quando o arquivo passa por
    # sistemas diferentes.
    for esperado in sch.ARQUIVOS:
        if esperado.lower() == limpo.lower():
            return esperado
    raise ArquivoRecusado(
        f"'{limpo}' não é um dos arquivos que o sistema conhece. "
        f"O nome precisa ser exatamente igual ao da planilha original."
    )


def conferir(nome_enviado: str, conteudo: bytes) -> tuple[str, list[str]]:
    """Confere o arquivo antes de qualquer escrita.

    Devolve (nome_oficial, abas_encontradas) ou levanta ArquivoRecusado.
    """
    nome = _resolver_nome(nome_enviado)

    if not conteudo:
        raise ArquivoRecusado("O arquivo chegou vazio.")
    if len(conteudo) > LIMITE_BYTES:
        raise ArquivoRecusado(
            f"O arquivo tem {len(conteudo) / (1024 * 1024):.1f} MB e o limite "
            f"é {LIMITE_BYTES // (1024 * 1024)} MB."
        )
    if not conteudo.startswith(ASSINATURA_XLSX):
        raise ArquivoRecusado(
            "Isso não é um .xlsx. Se a planilha estiver em .xls antigo, abra "
            "no Excel e salve como .xlsx."
        )

    try:
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True)
    except Exception as erro:
        raise ArquivoRecusado(
            f"Não consegui abrir a planilha: {type(erro).__name__}. "
            f"O arquivo pode estar corrompido."
        ) from erro

    try:
        abas = list(wb.sheetnames)
    finally:
        wb.close()

    presentes = {a.strip().upper() for a in abas}
    faltantes = [
        a
        for a in sch.ARQUIVOS[nome].abas_obrigatorias
        if a.strip().upper() not in presentes
    ]
    if faltantes:
        raise ArquivoRecusado(
            f"A planilha não tem a(s) aba(s) {', '.join(faltantes)}. "
            f"Confira se enviou o arquivo certo: o esperado é "
            f"'{sch.ARQUIVOS[nome].rotulo}'."
        )
    return nome, abas


# ---------------------------------------------------------------------------
# Gravacao
# ---------------------------------------------------------------------------


def _garantir_pasta(caminho: str) -> None:
    os.makedirs(caminho, exist_ok=True)


def _guardar_anterior(base: str, nome: str) -> Optional[str]:
    """Copia a versao atual para _backups antes de substituir."""
    origem = os.path.join(base, nome)
    if not os.path.exists(origem):
        return None
    pasta = os.path.join(base, sch.PASTA_BACKUPS)
    _garantir_pasta(pasta)
    carimbo = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    raiz, extensao = os.path.splitext(nome)
    destino = os.path.join(pasta, f"{raiz}.{carimbo}{extensao}")
    shutil.copy2(origem, destino)
    return destino


def _registrar(base: str, evento: dict) -> None:
    """Anota o envio na auditoria. Uma linha JSON por evento."""
    pasta = os.path.join(base, sch.PASTA_AUDITORIA)
    _garantir_pasta(pasta)
    caminho = os.path.join(pasta, "arquivos.jsonl")
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


@dataclass
class Recebido:
    nome: str
    rotulo: str
    tamanho: int
    substituiu: bool
    backup: Optional[str]
    abas: int


def diagnosticar_caminho(base: str, nome: str) -> Optional[str]:
    """Explica, antes de tentar gravar, por que o caminho nao vai funcionar.

    O caso real: no Windows o caminho completo nao pode passar de 260
    caracteres, e os nomes dessas planilhas ja tem 75. Sem esta checagem o
    erro que chega e 'No such file or directory', que manda quem esta
    depurando procurar problema no volume.
    """
    if os.name != "nt":
        return None
    completo = os.path.join(base, nome) + ".parcial"
    if len(completo) <= 259:
        return None
    return (
        f"O caminho ficaria com {len(completo)} caracteres e o Windows para "
        f"em 260. A pasta '{base}' é funda demais para nomes de arquivo "
        f"deste tamanho. Use uma pasta mais curta em PASTA_PLANILHAS. "
        f"No Railway isso não acontece, o limite é do Windows."
    )


def receber(base: str, nome_enviado: str, conteudo: bytes, usuario: str) -> Recebido:
    """Confere e coloca o arquivo na pasta. Levanta ArquivoRecusado se nao passar."""
    nome, abas = conferir(nome_enviado, conteudo)

    problema = diagnosticar_caminho(base, nome)
    if problema:
        raise ArquivoRecusado(problema)

    _garantir_pasta(base)
    destino = os.path.join(base, nome)
    ja_existia = os.path.exists(destino)

    backup = _guardar_anterior(base, nome)

    # Grava ao lado e troca de uma vez: se cair no meio, o arquivo bom
    # continua inteiro no lugar.
    temporario = destino + ".parcial"
    try:
        with open(temporario, "wb") as f:
            f.write(conteudo)
        os.replace(temporario, destino)
    except Exception:
        if os.path.exists(temporario):
            os.remove(temporario)
        raise

    _registrar(
        base,
        {
            "quando": dt.datetime.now().isoformat(timespec="seconds"),
            "usuario": usuario,
            "operacao": "envio_de_planilha",
            "arquivo": nome,
            "bytes": len(conteudo),
            "abas": len(abas),
            "substituiu_versao_anterior": ja_existia,
            "backup": os.path.basename(backup) if backup else None,
        },
    )

    return Recebido(
        nome=nome,
        rotulo=sch.ARQUIVOS[nome].rotulo,
        tamanho=len(conteudo),
        substituiu=ja_existia,
        backup=os.path.basename(backup) if backup else None,
        abas=len(abas),
    )


def chave_de_sessao_persistida(base: str) -> str:
    """Chave de assinatura do cookie, guardada no volume.

    Existe para nao obrigar ninguem a inventar e colar uma string aleatoria no
    painel. Fica fora das planilhas, num arquivo proprio, e e criada uma vez.
    """
    pasta = os.path.join(base, sch.PASTA_AUDITORIA)
    _garantir_pasta(pasta)
    caminho = os.path.join(pasta, "chave-sessao.txt")
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            guardada = f.read().strip()
        if len(guardada) >= 32:
            return guardada
    nova = secrets.token_hex(32)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(nova)
    return nova


def historico(base: str, limite: int = 20) -> list[dict]:
    """Ultimos envios registrados na auditoria."""
    caminho = os.path.join(base, sch.PASTA_AUDITORIA, "arquivos.jsonl")
    if not os.path.exists(caminho):
        return []
    linhas = []
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                linhas.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    return list(reversed(linhas))[:limite]
