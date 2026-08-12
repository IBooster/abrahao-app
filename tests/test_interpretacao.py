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


# ---------------------------------------------------------------------------
# Nunca responder a mesma coisa para tudo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frase",
    ["oi", "bom dia", "obrigado", "xyz abc 123", "???", "asdf"],
)
def test_frase_sem_sentido_nao_vira_consulta(p, frase):
    """O fallback nao pode ser uma consulta.

    Antes, qualquer frase desconhecida caia em posicao_geral: "oi" e "obrigado"
    devolviam o painel do ano inteiro, e o chat parecia travado numa resposta
    so. Agora ele admite que nao entendeu.
    """
    escolha = p.escolher(frase, "")
    assert escolha.consulta is None, (
        f"'{frase}' virou a consulta '{escolha.consulta}'. Frase que o sistema "
        f"nao entende deve dizer que nao entendeu."
    )


@pytest.mark.parametrize(
    "frase,esperado",
    [
        ("qual cliente paga mais?", "ranking_clientes"),
        ("quanto gastamos com aluguel?", "despesas_por_categoria"),
        ("em que gastamos mais este mês?", "despesas_por_categoria"),
        ("quanto faturamos em julho?", "faturamento"),
        ("quanto o BMG nos deve?", "cliente_posicao"),
        ("quanto saiu do Santander?", "movimento_conta"),
        ("como estamos?", "posicao_geral"),
    ],
)
def test_pergunta_vai_para_a_consulta_certa(p, frase, esperado):
    assert p.escolher(frase, "").consulta == esperado


def test_categoria_e_extraida(p):
    """"com aluguel" precisa filtrar, senao devolve todas as categorias."""
    assert p.escolher("quanto gastamos com aluguel?", "").parametros.get(
        "categoria"
    ) == "ALUGUEL"


# ---------------------------------------------------------------------------
# Continuidade da conversa
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frase",
    [
        "isso é apenas de honorário mensal ou é despesa operacional no total?",
        "e o resto?",
        "esse valor inclui folha?",
        "por que tanto?",
    ],
)
def test_pergunta_de_continuidade_nao_repete_a_consulta(p, frase):
    """Pergunta sobre a resposta anterior nao pode devolver a mesma coisa.

    Foi o que aconteceu num teste real: o usuario perguntou se o total era so
    de honorario, e recebeu de novo o mesmo card de despesas por categoria.
    """
    historico = [{
        "pergunta": "quanto gastamos em 2026?",
        "consulta": "despesas_por_categoria",
        "parametros": {"ano": 2026},
        "resumo": "R$ 3.964.969,70 em despesa operacional em 2026.",
        "numeros": {"total": 3964969.70, "categorias": 40},
        "detalhe": "Remuneracao: R$ 2.083.130,49",
    }]
    escolha = p.escolher(frase, "", historico)
    assert escolha.consulta is None, (
        f"'{frase}' repetiu a consulta '{escolha.consulta}' em vez de "
        f"responder sobre o turno anterior."
    )
    assert escolha.resposta_livre, "Deve explicar por que não consegue."


def test_sem_historico_nao_trata_como_continuidade(p):
    """Na primeira mensagem nao ha turno anterior a que se referir."""
    escolha = p.escolher("quanto gastamos com aluguel?", "", [])
    assert escolha.consulta == "despesas_por_categoria"


def test_anthropic_manda_o_historico_como_turnos():
    """O historico precisa ir como mensagens, nao colado no system.

    Sem isso o modelo nao tem a que se referir quando a pessoa diz "isso".
    """
    from app.llm.provedores import ProvedorAnthropic

    capturado = {}

    class FakeMessages:
        def create(self, **kwargs):
            capturado.update(kwargs)

            class R:
                content = [type("B", (), {"type": "text", "text": '{"consulta": null, "resposta_livre": "ok"}'})()]

            return R()

    class FakeCliente:
        messages = FakeMessages()

    prov = ProvedorAnthropic(E.CATALOGO)
    prov._cliente = FakeCliente()

    historico = [{
        "pergunta": "quanto gastamos em 2026?",
        "consulta": "despesas_por_categoria",
        "parametros": {"ano": 2026},
        "resumo": "R$ 3.964.969,70 em despesa operacional.",
        "numeros": {"total": 3964969.70},
        "detalhe": "Remuneracao: R$ 2.083.130,49",
    }]
    prov.escolher("isso inclui folha?", "CATALOGO", historico)

    mensagens = capturado["messages"]
    assert len(mensagens) == 3, "Esperava turno anterior (2) + pergunta atual"
    assert mensagens[0]["role"] == "user"
    assert mensagens[1]["role"] == "assistant"
    assert "3964969.7" in mensagens[1]["content"], (
        "O resumo do turno precisa carregar os números, senão o modelo não "
        "consegue responder sem refazer a consulta."
    )
    assert mensagens[2]["content"] == "isso inclui folha?"
