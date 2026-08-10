# -*- coding: utf-8 -*-
"""Testes do interpretador de frases.

Nasceram de um teste real que deu errado: a usuaria escreveu "a nota foi
emitida hoje, mas ainda nao recebemos o pagamento" e o sistema entendeu
RECEBIMENTO, por causa da palavra "recebemos". Negacao e contexto passam a
ser cobertos por teste.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.llm.provedores import ProvedorRegras  # noqa: E402
from app.queries import engine as E  # noqa: E402


@pytest.fixture
def p():
    return ProvedorRegras(E.CATALOGO)


FRASE_REAL = (
    "Entrou um cliente novo, a ABC Participações Ltda. Fechamos um contrato "
    "de honorários mensais de R$ 30.000, começando agora em agosto. A nota "
    "deve ser emitida todo dia 5 e o pagamento vence todo dia 15. A primeira "
    "nota foi emitida hoje, referente aos honorários de agosto, mas ainda "
    "não recebemos o pagamento. Cadastre o cliente e atualize todas as "
    "planilhas financeiras necessárias."
)


# ---------------------------------------------------------------------------
# Negacao
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frase",
    [
        FRASE_REAL,
        "A primeira nota foi emitida hoje mas ainda não recebemos",
        "emitimos a nota mas o cliente ainda não pagou",
    ],
)
def test_nao_recebemos_nao_e_recebimento(p, frase):
    """"ainda nao recebemos" jamais pode virar baixa de recebimento."""
    escolha = p.escolher(frase, "")
    assert escolha.operacao != "recebimento", (
        "Negacao ignorada: o sistema entendeu o oposto do que foi dito."
    )


def test_frase_real_e_nota_emitida(p):
    escolha = p.escolher(FRASE_REAL, "")
    assert escolha.operacao == "nota_emitida"
    assert escolha.dados.get("valor_bruto") == 30000.0
    assert "ABC" in (escolha.dados.get("cliente") or "")


# ---------------------------------------------------------------------------
# Emitir nao e receber
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frase,esperado",
    [
        ("teve uma nota do BMG de 100 mil", "nota_emitida"),
        ("emitimos uma nota de 50 mil para a FLAPA", "nota_emitida"),
        ("nota para a T Mining Mineração de 10 mil", "nota_emitida"),
        ("recebemos a nota 240/2026", "recebimento"),
        ("o BMG pagou a nota 240/2026", "recebimento"),
        ("o dinheiro do BMG caiu hoje", "recebimento"),
    ],
)
def test_operacao_correta(p, frase, esperado):
    assert p.escolher(frase, "").operacao == esperado


# ---------------------------------------------------------------------------
# Pergunta nunca vira lancamento
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frase",
    [
        "Quanto faturamos em julho?",
        "Quais guias pagamos e ainda não foram reembolsadas?",
        "Quanto pagamos de guias em julho?",
        "Quanto o BMG nos deve?",
        "entrou um cliente novo",
    ],
)
def test_pergunta_nao_vira_lancamento(p, frase):
    escolha = p.escolher(frase, "")
    assert escolha.operacao is None, (
        f"'{frase}' foi lida como lancamento. Consulta nunca escreve."
    )


# ---------------------------------------------------------------------------
# Extracao de campos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frase,esperado",
    [
        ("nota de 50 mil para a FLAPA", 50000.0),
        ("nota de R$ 1.234,56 para a FLAPA", 1234.56),
        ("nota de 30.000 para a FLAPA", 30000.0),
        ("nota de 1,5 milhão para a FLAPA", 1500000.0),
    ],
)
def test_extrai_valor(p, frase, esperado):
    assert p.escolher(frase, "").dados.get("valor_bruto") == esperado


def test_numero_da_nota_nao_vira_valor(p):
    """"240/2026" e numero de NF, nao R$ 240."""
    dados = p.escolher("recebemos a nota 240/2026", "").dados
    assert dados.get("numero") == "240/2026"
    assert dados.get("valor") is None


@pytest.mark.parametrize(
    "frase,esperado",
    [
        ("nova nota da FCF Holding Ltda de 1.800", "FCF Holding Ltda"),
        ("nota para a T Mining Mineração de 10 mil", "T Mining Mineração"),
        ("teve uma nota do BMG de 100 mil", "BMG"),
    ],
)
def test_nome_do_cliente_vem_inteiro(p, frase, esperado):
    """O nome vai para a planilha: truncar perde a identificacao do cliente."""
    assert p.escolher(frase, "").dados.get("cliente") == esperado
