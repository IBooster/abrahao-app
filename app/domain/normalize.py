# -*- coding: utf-8 -*-
"""Normalizacao de valores lidos das planilhas.

As planilhas sao preenchidas por pessoas, entao o mesmo dado aparece em varias
formas: data como texto, valor como "R$ 12.396,22", cliente como "BMG",
"BMG (negocial)" ou "BMG(honorarios iniciais)", aba com espaco no fim.
Tudo que lida com essa bagunca mora aqui.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------


def sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def chave(texto: Any) -> str:
    """Forma canonica para comparar nomes: sem acento, minusculo, sem ruido."""
    if texto is None:
        return ""
    t = sem_acento(str(texto)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def texto(valor: Any) -> Optional[str]:
    """Texto limpo, ou None quando a celula esta vazia ou so tem tracinho."""
    if valor is None:
        return None
    s = str(valor).strip()
    if not s or s in {"-", "--", "?", "????", "?????"}:
        return None
    return s


# ---------------------------------------------------------------------------
# Numeros
# ---------------------------------------------------------------------------

_RE_MOEDA = re.compile(r"[^\d,.\-]")


def numero(valor: Any) -> Optional[float]:
    """Converte celula em float.

    Aceita numero nativo e tambem texto no formato brasileiro ("R$ 12.396,22"),
    que e como as abas historicas guardam valor.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)

    s = str(valor).strip()
    if not s or s in {"-", "--"}:
        return None

    s = _RE_MOEDA.sub("", s)
    if not s or s in {"-", ",", "."}:
        return None

    # Formato brasileiro: ponto separa milhar, virgula separa decimal.
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def zero(valor: Any) -> float:
    n = numero(valor)
    return n if n is not None else 0.0


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------

_FORMATOS_DATA = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")


def data(valor: Any) -> Optional[dt.date]:
    """Converte celula em date. Retorna None quando nao for data reconhecivel."""
    if valor is None:
        return None
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor

    s = str(valor).strip()
    if not s:
        return None

    # Pega a primeira data que aparecer no texto ("recebemos 27/01/2026").
    achado = re.search(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\b", s)
    alvo = achado.group(1) if achado else s
    for fmt in _FORMATOS_DATA:
        try:
            return dt.datetime.strptime(alvo, fmt).date()
        except ValueError:
            continue
    return None


def contem_pendente(valor: Any) -> bool:
    if valor is None:
        return False
    return "PENDENTE" in str(valor).strip().upper()


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------

# O mesmo cliente aparece com sufixo de projeto no faturamento e com nome
# curto no razao. Para agrupar, reduzimos ao radical.
_SUFIXOS_PROJETO = (
    "negocial",
    "honorarios iniciais",
    "honorarios finais",
    "massificado",
    "cartao",
    "seguro",
    "cnc",
    "controladoria",
    "cnpj rafaela",
)

_RE_PARENTESES = re.compile(r"\([^)]*\)")
_RE_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")


def radical_cliente(nome: Any) -> str:
    """Reduz o nome do cliente ao radical usado para agrupar.

    "BMG (negocial)" -> "bmg"
    "BMG(honorarios iniciais)" -> "bmg"
    "FORTALEZA - 03.205.629/0001-66" -> "fortaleza"
    """
    if nome is None:
        return ""
    s = str(nome)
    s = _RE_CNPJ.sub(" ", s)
    s = _RE_PARENTESES.sub(" ", s)
    k = chave(s)
    for suf in _SUFIXOS_PROJETO:
        if k.endswith(" " + suf):
            k = k[: -len(suf) - 1].strip()
    k = k.strip(" -")
    return k


def cliente_bate(consulta: str, nome: Any) -> bool:
    """Casa o que a usuaria digitou com o nome que esta na planilha."""
    c = radical_cliente(consulta)
    n = radical_cliente(nome)
    if not c or not n:
        return False
    if c == n:
        return True
    # Prefixo por palavra inteira, para "shopping" achar "shopping norte"
    # sem que "arg" ache "argamassa".
    return n.startswith(c + " ") or c.startswith(n + " ")


# ---------------------------------------------------------------------------
# Abas
# ---------------------------------------------------------------------------

_MESES_NUM = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def mes_de_aba(nome_aba: str) -> Optional[tuple[int, int]]:
    """Le "julho 2026 " (com espaco no fim, como esta no arquivo) -> (7, 2026)."""
    k = chave(nome_aba)
    partes = k.split()
    if len(partes) < 2:
        return None
    mes = _MESES_NUM.get(partes[0])
    if mes is None:
        return None
    try:
        ano = int(partes[-1])
    except ValueError:
        return None
    return mes, ano


def numero_mes(nome: Any) -> Optional[int]:
    """Le "julho", "jul", "07" ou "7" -> 7."""
    if nome is None:
        return None
    if isinstance(nome, int):
        return nome if 1 <= nome <= 12 else None
    k = chave(nome)
    if k in _MESES_NUM:
        return _MESES_NUM[k]
    for nome_mes, num in _MESES_NUM.items():
        if k and nome_mes.startswith(k):
            return num
    if k.isdigit():
        n = int(k)
        if 1 <= n <= 12:
            return n
    return None


NOME_MES = {v: k for k, v in _MESES_NUM.items()}


def rotulo_mes(mes: int, ano: int) -> str:
    nome = NOME_MES.get(mes, str(mes))
    return f"{nome}/{ano}"


# ---------------------------------------------------------------------------
# Formatacao para exibicao
# ---------------------------------------------------------------------------


def moeda(valor: Optional[float]) -> str:
    if valor is None:
        return "-"
    inteiro = f"{abs(valor):,.2f}"
    inteiro = inteiro.replace(",", "@").replace(".", ",").replace("@", ".")
    sinal = "-" if valor < 0 else ""
    return f"{sinal}R$ {inteiro}"


def data_br(valor: Optional[dt.date]) -> str:
    if valor is None:
        return "-"
    return valor.strftime("%d/%m/%Y")


def extrair_lote(descricao: Any) -> Optional[str]:
    """"REEMBOLSO 55/26 - 29/07/2026 A 30/07/2026" -> "55/26"."""
    if descricao is None:
        return None
    achado = re.search(r"REEMBOLSO\s+(\d{1,3}\s*/\s*\d{2})", str(descricao).upper())
    if achado:
        return achado.group(1).replace(" ", "")
    achado = re.search(r"REEMBOLSO\s+(\d{1,3})\b", str(descricao).upper())
    if achado:
        return achado.group(1)
    return None
