# -*- coding: utf-8 -*-
"""Testes do motor de lancamentos.

Cercam as promessas do modulo: propor nao escreve, aplicar so escreve o que
estava na proposta, e as recusas acontecem ANTES de qualquer gravacao.

Rodam sobre copias das planilhas reais, nunca sobre os originais.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import lancamentos as L  # noqa: E402
from app.domain import schema as sch  # noqa: E402
from app.domain.loader import carregar  # noqa: E402


def _origem() -> str:
    from app.config import CONFIG

    return CONFIG.pasta_planilhas


@pytest.fixture
def base(tmp_path):
    """Copia das planilhas reais num diretorio descartavel."""
    origem = _origem()
    if not os.path.isdir(origem):
        pytest.skip("Planilhas nao disponiveis neste ambiente.")
    faltando = [
        f for f in sch.ARQUIVOS_ESPERADOS
        if not os.path.exists(os.path.join(origem, f))
    ]
    if faltando:
        pytest.skip("Planilhas incompletas neste ambiente.")

    destino = tmp_path / "planilhas"
    destino.mkdir()
    for f in sch.ARQUIVOS_ESPERADOS:
        shutil.copy2(os.path.join(origem, f), destino / f)
    return str(destino)


def _assinaturas(base: str) -> dict:
    return {
        f: (os.stat(os.path.join(base, f)).st_mtime_ns,
            os.stat(os.path.join(base, f)).st_size)
        for f in sch.ARQUIVOS_ESPERADOS
    }


# ---------------------------------------------------------------------------
# propor() nunca escreve
# ---------------------------------------------------------------------------


def test_propor_nao_toca_em_arquivo(base):
    antes = _assinaturas(base)
    ix = carregar(base)

    L.propor(ix, "nota_emitida", {"cliente": "BMG", "valor_bruto": 100000})
    L.propor(ix, "nota_emitida", {"cliente": "DESCONHECIDO", "valor_bruto": 1})
    L.propor(ix, "recebimento", {"cliente": "BMG"})

    assert _assinaturas(base) == antes, "propor() alterou arquivo. Ela so monta."


# ---------------------------------------------------------------------------
# Recusas, e todas antes de gravar
# ---------------------------------------------------------------------------


def test_pergunta_em_vez_de_chutar_o_cnpj(base):
    ix = carregar(base)
    p = L.propor(ix, "nota_emitida", {"cliente": "CLIENTE QUE NAO EXISTE", "valor_bruto": 1000})
    assert not p.pronta
    assert any("principal" in f.lower() for f in p.faltando)


def test_pergunta_quando_a_retencao_do_cliente_varia(base):
    """A FLAPA usou cinco retencoes diferentes em 2026: nao da para inferir."""
    ix = carregar(base)
    p = L.propor(ix, "nota_emitida", {"cliente": "FLAPA", "valor_bruto": 50000})
    assert not p.pronta
    assert any("líquido" in f for f in p.faltando)


def test_aplicar_recusa_proposta_incompleta(base):
    ix = carregar(base)
    p = L.propor(ix, "nota_emitida", {"cliente": "FLAPA", "valor_bruto": 50000})
    antes = _assinaturas(base)
    with pytest.raises(L.LancamentoRecusado):
        L.aplicar(base, p, "teste")
    assert _assinaturas(base) == antes


def test_nunca_escreve_no_arquivo_da_dre(base):
    p = L.Proposta(token="t", tipo="teste", resumo="r")
    p.alvos = [L.Alvo(
        arquivo=sch.ARQ_DRE_BMG, aba="GERAL", linha=200, acao="nova linha",
        celulas=[L.Celula("A200", "x", "y", "y")],
    )]
    antes = _assinaturas(base)
    with pytest.raises(L.LancamentoRecusado) as erro:
        L.aplicar(base, p, "teste")
    assert "DRE" in str(erro.value)
    assert _assinaturas(base) == antes


def test_nunca_escreve_na_matriz_mensal(base):
    """A aba 2026 e preenchida a mao pelo financeiro no fechamento."""
    p = L.Proposta(token="t", tipo="teste", resumo="r")
    p.alvos = [L.Alvo(
        arquivo=sch.ARQ_FLUXO, aba=sch.MATRIZ.aba, linha=200, acao="nova linha",
        celulas=[L.Celula("B200", "x", 1, "1")],
    )]
    antes = _assinaturas(base)
    with pytest.raises(L.LancamentoRecusado) as erro:
        L.aplicar(base, p, "teste")
    assert "fechamento" in str(erro.value).lower()
    assert _assinaturas(base) == antes


def test_nao_sobrescreve_celula_ja_preenchida(base):
    """Se a planilha mudou desde a proposta, aborta em vez de atropelar."""
    ix = carregar(base)
    alguma = next(n for n in ix.notas if n.emitida and not n.bloco_secundario)
    ent = sch.ENTIDADES[alguma.entidade]

    p = L.Proposta(token="t", tipo="teste", resumo="r")
    p.alvos = [L.Alvo(
        arquivo=ent.arquivo, aba=alguma.aba, linha=alguma.linha, acao="nova linha",
        celulas=[L.Celula(f"B{alguma.linha}", "Cliente", "OUTRO", "OUTRO")],
    )]
    with pytest.raises(L.LancamentoRecusado) as erro:
        L.aplicar(base, p, "teste")
    assert "já tem" in str(erro.value)


# ---------------------------------------------------------------------------
# Ciclo completo
# ---------------------------------------------------------------------------


def test_nota_emitida_grava_e_e_relida(base):
    ix = carregar(base)
    p = L.propor(ix, "nota_emitida", {
        "cliente": "BMG", "valor_bruto": 100000,
        "numero": "999/2026", "observacoes": "Teste automatizado",
    })
    assert p.pronta, p.faltando

    feito = L.aplicar(base, p, "teste")
    assert feito["celulas"]

    nova = [n for n in carregar(base).notas if (n.numero or "") == "999/2026"]
    assert len(nova) == 1
    n = nova[0]
    assert n.cliente == "BMG"
    assert n.valor_bruto == 100000
    assert n.estado == "pendente", "Nota emitida nasce PENDENTE, nao recebida."
    assert n.data_recebimento is None, "Emitir nao e receber."


def test_recebimento_da_baixa_e_lanca_no_razao(base):
    ix = carregar(base)
    p = L.propor(ix, "nota_emitida", {
        "cliente": "BMG", "valor_bruto": 100000, "numero": "998/2026",
    })
    L.aplicar(base, p, "teste")

    ix2 = carregar(base)
    p2 = L.propor(ix2, "recebimento", {"numero": "998/2026"})
    assert p2.pronta, p2.faltando
    assert len(p2.alvos) == 2, "Recebimento escreve na nota E no razao do banco."

    L.aplicar(base, p2, "teste")

    ix3 = carregar(base)
    n = next(x for x in ix3.notas if (x.numero or "") == "998/2026")
    assert n.estado == "recebida"
    assert n.data_recebimento is not None

    entradas = [
        l for l in ix3.lancamentos
        if l.historico and "998/2026" in l.historico
    ]
    assert len(entradas) == 1
    assert entradas[0].entrada == n.valor
    assert entradas[0].natureza == "faturamento"


def test_aplicar_guarda_copia_e_registra_auditoria(base):
    ix = carregar(base)
    p = L.propor(ix, "nota_emitida", {
        "cliente": "BMG", "valor_bruto": 5000, "numero": "997/2026",
    })
    feito = L.aplicar(base, p, "liza")

    assert feito["backups"], "Nenhuma copia guardada antes de gravar."
    copias = list((Path(base) / sch.PASTA_BACKUPS).glob("*.xlsx"))
    assert copias

    from app import arquivos

    registros = arquivos.historico(base)
    assert registros
    ultimo = registros[0]
    assert ultimo["operacao"] == "nota_emitida"
    assert ultimo["usuario"] == "liza"
    assert ultimo["celulas"]


def test_consultas_enxergam_o_lancamento(base):
    from app.queries import engine

    antes = engine.executar(carregar(base), "a_receber", {})
    p = L.propor(carregar(base), "nota_emitida", {
        "cliente": "BMG", "valor_bruto": 10000, "numero": "996/2026",
    })
    L.aplicar(base, p, "teste")
    depois = engine.executar(carregar(base), "a_receber", {})

    assert depois.numeros["pendente"] > antes.numeros["pendente"]
