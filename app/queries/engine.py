# -*- coding: utf-8 -*-
"""Motor de consultas.

Cada funcao aqui e deterministica: recebe parametros tipados, le o indice em
memoria e devolve um Resultado. Nenhuma delas escreve. O modelo de linguagem
escolhe QUAL funcao chamar e com quais parametros; ele nunca calcula o numero
nem decide de onde o dado vem.

Toda funcao devolve, alem do numero, a lista de linhas que o produziram - para
que qualquer resposta possa ser conferida contra a planilha.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..domain import normalize as nz
from ..domain import schema as sch
from ..domain.models import (
    ESTADO_PENDENTE,
    ESTADO_PREVISTA,
    ESTADO_RECEBIDA,
    ESTADO_SEM_BAIXA,
    Indice,
    Nota,
)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------


@dataclass
class Linha:
    """Uma evidencia: de onde saiu o numero."""

    rotulo: str
    valor: Optional[float] = None
    detalhe: Optional[str] = None
    origem: Optional[str] = None  # arquivo > aba > linha
    estado: Optional[str] = None


@dataclass
class Resultado:
    titulo: str
    resumo: str
    numeros: dict[str, float] = field(default_factory=dict)
    linhas: list[Linha] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    fonte: list[str] = field(default_factory=list)
    faltou: Optional[str] = None  # pergunta a fazer quando falta parametro


def _origem_nota(n: Nota) -> str:
    ent = sch.ENTIDADES[n.entidade]
    return f"{ent.arquivo} > {n.aba.strip()} > linha {n.linha}"


ROTULO_ESTADO = {
    ESTADO_PREVISTA: "prevista, sem NF",
    ESTADO_PENDENTE: "faturada, marcada PENDENTE",
    ESTADO_SEM_BAIXA: "faturada, sem baixa registrada",
    ESTADO_RECEBIDA: "recebida",
}


# ---------------------------------------------------------------------------
# Filtros auxiliares
# ---------------------------------------------------------------------------


def _notas_do_periodo(
    ix: Indice,
    mes: Optional[int],
    ano: Optional[int],
    entidade: Optional[str],
) -> list[Nota]:
    notas = [n for n in ix.notas if not n.bloco_secundario]
    if mes is not None:
        notas = [n for n in notas if n.mes == mes]
    if ano is not None:
        notas = [n for n in notas if n.ano == ano]
    if entidade:
        notas = [n for n in notas if n.entidade == entidade]
    return notas


def _lancamentos(ix: Indice) -> list:
    """Lancamentos que valem para calculo.

    Exclui as copias: linhas que repetem, em outra aba, movimento que ja esta
    na aba da propria conta. Ver schema.e_espelho.
    """
    return [l for l in ix.lancamentos if not l.espelho]


def _resolver_entidade(nome: Optional[str]) -> Optional[str]:
    if not nome:
        return None
    k = nz.chave(nome)
    for codigo, ent in sch.ENTIDADES.items():
        if k == codigo or any(k == nz.chave(a) or a in k for a in ent.apelidos):
            return codigo
    return None


def _resolver_conta(nome: Optional[str]) -> Optional[sch.Conta]:
    if not nome:
        return None
    k = nz.chave(nome)
    for conta in sch.CONTAS.values():
        if k == conta.codigo or any(nz.chave(a) == k for a in conta.apelidos):
            return conta
    for conta in sch.CONTAS.values():
        if any(nz.chave(a) in k for a in conta.apelidos):
            return conta
    return None


def _rotulo_periodo(mes: Optional[int], ano: Optional[int]) -> str:
    if mes and ano:
        return nz.rotulo_mes(mes, ano)
    if ano:
        return str(ano)
    if mes:
        return nz.NOME_MES.get(mes, str(mes))
    return "todo o periodo carregado"


# ---------------------------------------------------------------------------
# 1. Faturamento do periodo
# ---------------------------------------------------------------------------


def faturamento(
    ix: Indice,
    mes: Optional[int] = None,
    ano: Optional[int] = 2026,
    entidade: Optional[str] = None,
    **_: Any,
) -> Resultado:
    """Quanto foi faturado, recebido e o que segue em aberto no periodo."""
    codigo = _resolver_entidade(entidade)
    notas = _notas_do_periodo(ix, mes, ano, codigo)

    emitidas = [n for n in notas if n.emitida]
    recebidas = [n for n in emitidas if n.estado == ESTADO_RECEBIDA]
    pendentes = [n for n in emitidas if n.estado == ESTADO_PENDENTE]
    sem_baixa = [n for n in emitidas if n.estado == ESTADO_SEM_BAIXA]
    previstas = [n for n in notas if not n.emitida]

    soma = lambda ns: sum(n.valor for n in ns)
    periodo = _rotulo_periodo(mes, ano)
    if codigo:
        quem, verbo = sch.ENTIDADES[codigo].nome, "emitiu"
    else:
        quem, verbo = "os dois CNPJs", "emitiram"

    res = Resultado(
        titulo=f"Faturamento de {periodo}",
        resumo=(
            f"Em {periodo}, {quem} {verbo} {len(emitidas)} notas somando "
            f"{nz.moeda(soma(emitidas))} líquidos. Desse total, "
            f"{nz.moeda(soma(recebidas))} já entrou em caixa."
        ),
        numeros={
            "faturado": soma(emitidas),
            "recebido": soma(recebidas),
            "pendente": soma(pendentes),
            "sem_baixa": soma(sem_baixa),
            "previsto": soma(previstas),
        },
        fonte=sorted({_origem_nota(n).split(" > ")[0] for n in notas}),
    )

    res.linhas = [
        Linha("Faturado (NF emitida)", soma(emitidas), f"{len(emitidas)} notas"),
        Linha("Recebido", soma(recebidas), f"{len(recebidas)} notas"),
        Linha("Em aberto, marcado PENDENTE", soma(pendentes), f"{len(pendentes)} notas"),
    ]
    if sem_baixa:
        res.linhas.append(
            Linha(
                "Em aberto, sem baixa registrada",
                soma(sem_baixa),
                f"{len(sem_baixa)} notas",
            )
        )
    if previstas:
        res.linhas.append(
            Linha(
                "Previsto, nota ainda não emitida",
                soma(previstas),
                f"{len(previstas)} linhas",
            )
        )

    if sem_baixa:
        res.avisos.append(
            f"{len(sem_baixa)} notas emitidas não têm data nem marcador na "
            f"coluna de recebimento ({nz.moeda(soma(sem_baixa))}). Não contei "
            f"como recebidas nem como pendentes. Pergunta 12, em aberto."
        )
    return res


# ---------------------------------------------------------------------------
# 2. Recebimentos do periodo (regime de caixa)
# ---------------------------------------------------------------------------


def recebimentos(
    ix: Indice,
    mes: Optional[int] = None,
    ano: Optional[int] = 2026,
    entidade: Optional[str] = None,
    **_: Any,
) -> Resultado:
    """Quanto efetivamente entrou, pela DATA DE RECEBIMENTO.

    Diferente de faturamento(): aqui o mes e o do recebimento, nao o da
    emissao. Uma nota de junho recebida em agosto conta em agosto.
    """
    codigo = _resolver_entidade(entidade)
    notas = [
        n
        for n in ix.notas
        if not n.bloco_secundario
        and n.estado == ESTADO_RECEBIDA
        and n.data_recebimento is not None
    ]
    if codigo:
        notas = [n for n in notas if n.entidade == codigo]
    if ano is not None:
        notas = [n for n in notas if n.data_recebimento.year == ano]
    if mes is not None:
        notas = [n for n in notas if n.data_recebimento.month == mes]

    total = sum(n.valor for n in notas)
    periodo = _rotulo_periodo(mes, ano)

    por_cliente: dict[str, float] = {}
    for n in notas:
        por_cliente[n.cliente or "(sem cliente)"] = por_cliente.get(
            n.cliente or "(sem cliente)", 0.0
        ) + n.valor

    res = Resultado(
        titulo=f"Recebimentos de {periodo}",
        resumo=(
            f"Entraram {nz.moeda(total)} em {periodo}, em {len(notas)} notas, "
            f"contados pela data de recebimento."
        ),
        numeros={"recebido": total, "notas": float(len(notas))},
        fonte=sorted({_origem_nota(n).split(" > ")[0] for n in notas}),
    )
    res.linhas = [
        Linha(cliente, valor)
        for cliente, valor in sorted(por_cliente.items(), key=lambda x: -x[1])
    ]
    return res


# ---------------------------------------------------------------------------
# 3. Contas a receber
# ---------------------------------------------------------------------------


def a_receber(
    ix: Indice,
    cliente: Optional[str] = None,
    entidade: Optional[str] = None,
    **_: Any,
) -> Resultado:
    """Tudo que foi faturado e ainda nao entrou."""
    codigo = _resolver_entidade(entidade)
    notas = [n for n in ix.notas if not n.bloco_secundario and n.em_aberto]
    if codigo:
        notas = [n for n in notas if n.entidade == codigo]
    if cliente:
        notas = [n for n in notas if nz.cliente_bate(cliente, n.cliente)]
        if not notas:
            return Resultado(
                titulo="Contas a receber",
                resumo=f"Não encontrei nota em aberto para '{cliente}'.",
                fonte=[],
            )

    pendentes = [n for n in notas if n.estado == ESTADO_PENDENTE]
    sem_baixa = [n for n in notas if n.estado == ESTADO_SEM_BAIXA]
    soma = lambda ns: sum(n.valor for n in ns)

    alvo = f" de {cliente}" if cliente else ""
    res = Resultado(
        titulo=f"Contas a receber{alvo}",
        resumo=(
            f"{nz.moeda(soma(pendentes))} em {len(pendentes)} notas marcadas "
            f"PENDENTE. Além disso, {nz.moeda(soma(sem_baixa))} em "
            f"{len(sem_baixa)} notas cuja coluna de recebimento ficou vazia."
        ),
        numeros={
            "pendente": soma(pendentes),
            "sem_baixa": soma(sem_baixa),
            "total": soma(notas),
        },
        fonte=sorted({_origem_nota(n).split(" > ")[0] for n in notas}),
    )
    for n in sorted(notas, key=lambda x: (x.ano, x.mes, x.linha)):
        res.linhas.append(
            Linha(
                rotulo=f"NF {n.numero} - {n.cliente}",
                valor=n.valor,
                detalhe=f"{nz.rotulo_mes(n.mes, n.ano)}"
                + (f" - {n.observacoes}" if n.observacoes else ""),
                origem=_origem_nota(n),
                estado=ROTULO_ESTADO.get(n.estado),
            )
        )
    if sem_baixa:
        res.avisos.append(
            "As notas sem marcador não estão declaradas como pendentes na "
            "planilha. Confirmar com o financeiro antes de cobrar."
        )
    return res


# ---------------------------------------------------------------------------
# 4. Posicao de um cliente
# ---------------------------------------------------------------------------


def cliente_posicao(
    ix: Indice, cliente: Optional[str] = None, **_: Any
) -> Resultado:
    """O que um cliente deve: notas em aberto mais reembolsos nao devolvidos."""
    if not cliente:
        return Resultado(
            titulo="Posição do cliente",
            resumo="",
            faltou="De qual cliente?",
        )

    notas = [
        n
        for n in ix.notas
        if not n.bloco_secundario and nz.cliente_bate(cliente, n.cliente)
    ]
    if not notas:
        candidatos = sorted(
            {
                n.cliente
                for n in ix.notas
                if n.cliente and nz.chave(cliente)[:3] in nz.chave(n.cliente)
            }
        )
        sugestao = (
            f" Talvez seja um destes: {', '.join(candidatos[:6])}."
            if candidatos
            else ""
        )
        return Resultado(
            titulo="Posição do cliente",
            resumo=f"Não encontrei '{cliente}' no faturamento de 2026.{sugestao}",
        )

    nome_real = max(
        {n.cliente for n in notas if n.cliente},
        key=lambda c: sum(1 for n in notas if n.cliente == c),
    )
    abertas = [n for n in notas if n.em_aberto]
    recebidas = [n for n in notas if n.estado == ESTADO_RECEBIDA]

    nds = [
        d
        for d in ix.notas_debito
        if d.em_aberto and nz.cliente_bate(cliente, d.cliente)
    ]
    total_nd = sum(d.valor or 0.0 for d in nds)
    total_notas = sum(n.valor for n in abertas)

    res = Resultado(
        titulo=f"Posição de {nome_real}",
        resumo=(
            f"{nome_real} deve {nz.moeda(total_notas + total_nd)}: "
            f"{nz.moeda(total_notas)} em {len(abertas)} notas em aberto"
            + (
                f" e {nz.moeda(total_nd)} em "
                + (
                    "1 nota de débito."
                    if len(nds) == 1
                    else f"{len(nds)} notas de débito."
                )
                if nds
                else "."
            )
            + f" Já pagou {nz.moeda(sum(n.valor for n in recebidas))} em 2026."
        ),
        numeros={
            "em_aberto": total_notas,
            "notas_debito": total_nd,
            "devido": total_notas + total_nd,
            "recebido_2026": sum(n.valor for n in recebidas),
        },
        fonte=sorted({_origem_nota(n).split(" > ")[0] for n in notas}),
    )
    for n in sorted(abertas, key=lambda x: (x.ano, x.mes, x.linha)):
        res.linhas.append(
            Linha(
                rotulo=f"NF {n.numero}",
                valor=n.valor,
                detalhe=f"{nz.rotulo_mes(n.mes, n.ano)}"
                + (f" - {n.observacoes}" if n.observacoes else ""),
                origem=_origem_nota(n),
                estado=ROTULO_ESTADO.get(n.estado),
            )
        )
    for d in nds:
        res.linhas.append(
            Linha(
                rotulo=f"ND {d.numero}",
                valor=d.valor,
                detalhe=d.despesas,
                origem=f"{sch.ARQ_FLUXO} > {d.aba} > linha {d.linha}",
                estado="nota de débito em aberto",
            )
        )
    return res


# ---------------------------------------------------------------------------
# 5. Reembolsos pendentes
# ---------------------------------------------------------------------------


def reembolsos_pendentes(ix: Indice, **_: Any) -> Resultado:
    """As tres trilhas de reembolso, somadas e discriminadas."""
    lotes = [l for l in ix.lotes if l.pendente]
    manuais = [m for m in ix.manuais if m.pendente and m.consolidado]
    nds = [d for d in ix.notas_debito if d.em_aberto]

    total_lotes = sum(l.valor for l in lotes)
    total_manuais = sum(m.valor for m in manuais)
    total_nds = sum(d.valor or 0.0 for d in nds)
    total = total_lotes + total_manuais + total_nds

    res = Resultado(
        titulo="Reembolsos em aberto",
        resumo=(
            f"{nz.moeda(total)} em aberto no total: "
            f"{nz.moeda(total_lotes)} em {len(lotes)} lotes de guias do BMG, "
            f"{nz.moeda(total_manuais)} em {len(manuais)} reembolsos manuais "
            f"por processo, e {nz.moeda(total_nds)} em {len(nds)} notas de "
            f"débito de outros clientes."
        ),
        numeros={
            "lotes": total_lotes,
            "manuais": total_manuais,
            "notas_debito": total_nds,
            "total": total,
        },
        fonte=[sch.ARQ_REEMBOLSOS, sch.ARQ_FLUXO],
    )

    for l in sorted(lotes, key=lambda x: x.linha):
        res.linhas.append(
            Linha(
                rotulo=f"Lote {l.numero_lote or '?'}",
                valor=l.valor,
                detalhe=l.descricao,
                origem=f"{sch.ARQ_REEMBOLSOS} > {l.aba} > linha {l.linha}",
                estado="lote de guias, aguardando o BMG",
            )
        )
    for m in sorted(manuais, key=lambda x: (x.ano_pendencia or 0, -x.valor)):
        res.linhas.append(
            Linha(
                rotulo=m.parte or "(sem parte)",
                valor=m.valor,
                detalhe=" - ".join(
                    p for p in (m.civ, m.chamado, m.observacao) if p
                ),
                origem=f"{sch.ARQ_REEMBOLSOS} > {m.aba} > linha {m.linha}",
                estado=m.status,
            )
        )
    for d in sorted(nds, key=lambda x: x.linha):
        res.linhas.append(
            Linha(
                rotulo=f"ND {d.numero} - {d.cliente}",
                valor=d.valor,
                detalhe=d.despesas,
                origem=f"{sch.ARQ_FLUXO} > {d.aba} > linha {d.linha}",
                estado="nota de débito em aberto",
            )
        )

    antigos = [m for m in manuais if (m.ano_pendencia or 9999) < 2026]
    if antigos:
        res.avisos.append(
            f"{len(antigos)} reembolsos manuais estão pendentes desde antes de "
            f"2026, somando {nz.moeda(sum(m.valor for m in antigos))}."
        )
    return res


# ---------------------------------------------------------------------------
# 6. Guias adiantadas
# ---------------------------------------------------------------------------


def guias_adiantadas(
    ix: Indice,
    mes: Optional[int] = None,
    ano: Optional[int] = 2026,
    **_: Any,
) -> Resultado:
    """Quanto o escritorio adiantou em guias judiciais no periodo."""
    lanc = [
        l
        for l in _lancamentos(ix)
        if l.natureza == "adiantamento" and l.saida > 0 and l.data is not None
    ]
    if ano is not None:
        lanc = [l for l in lanc if l.data.year == ano]
    if mes is not None:
        lanc = [l for l in lanc if l.data.month == mes]

    total = sum(l.saida for l in lanc)
    periodo = _rotulo_periodo(mes, ano)

    por_tipo: dict[str, float] = {}
    por_contrato: dict[str, float] = {}
    for l in lanc:
        d = (l.descricao or "?").strip().upper()
        por_tipo[d] = por_tipo.get(d, 0.0) + l.saida
        c = l.contrato or "(sem contrato)"
        por_contrato[c] = por_contrato.get(c, 0.0) + l.saida

    res = Resultado(
        titulo=f"Guias e depósitos adiantados em {periodo}",
        resumo=(
            f"O escritório adiantou {nz.moeda(total)} em {len(lanc)} "
            f"lançamentos em {periodo}."
        ),
        numeros={"adiantado": total, "lancamentos": float(len(lanc))},
        fonte=[sch.ARQ_FLUXO],
    )
    res.linhas = [
        Linha(tipo, valor, "por tipo de guia")
        for tipo, valor in sorted(por_tipo.items(), key=lambda x: -x[1])
    ] + [
        Linha(contrato, valor, "por cliente")
        for contrato, valor in sorted(por_contrato.items(), key=lambda x: -x[1])[:10]
    ]
    return res


def guias_sem_lote(ix: Indice, **_: Any) -> Resultado:
    """Guias pagas que ainda nao foram agrupadas em nenhum lote de cobranca."""
    lanc = [
        l
        for l in _lancamentos(ix)
        if l.natureza == "adiantamento"
        and l.saida > 0
        and l.conta == "inter"
        and not l.rotulo_reembolso
    ]
    total = sum(l.saida for l in lanc)
    res = Resultado(
        titulo="Guias pagas ainda sem lote",
        resumo=(
            f"{len(lanc)} guias pagas pelo Inter, somando {nz.moeda(total)}, "
            f"não têm rótulo de lote na coluna REEMBOLSO. Ou ainda não foram "
            f"fechadas em lote, ou o rótulo não foi preenchido."
        ),
        numeros={"total": total, "quantidade": float(len(lanc))},
        fonte=[sch.ARQ_FLUXO],
    )
    for l in sorted(lanc, key=lambda x: (x.data or dt.date.min), reverse=True)[:40]:
        res.linhas.append(
            Linha(
                rotulo=l.remetente or "(sem parte)",
                valor=l.saida,
                detalhe=f"{nz.data_br(l.data)} - {l.descricao}"
                + (f" - {l.historico}" if l.historico else ""),
                origem=f"{sch.ARQ_FLUXO} > {l.aba} > linha {l.linha}",
            )
        )
    return res


# ---------------------------------------------------------------------------
# 7. Movimento por conta
# ---------------------------------------------------------------------------


def movimento_conta(
    ix: Indice,
    conta: Optional[str] = None,
    mes: Optional[int] = None,
    ano: Optional[int] = 2026,
    **_: Any,
) -> Resultado:
    """Entradas e saidas de uma conta no periodo, separando transferencia."""
    c = _resolver_conta(conta)
    if c is None:
        nomes = ", ".join(x.rotulo for x in sch.CONTAS.values())
        return Resultado(
            titulo="Movimento por conta",
            resumo="",
            faltou=f"De qual conta? Tenho razão de: {nomes}.",
        )

    # conta_efetiva, nao conta: a aba SANTANDER abriga tres contas diferentes,
    # separadas pela coluna BANCO.
    lanc = [
        l
        for l in _lancamentos(ix)
        if l.conta_efetiva == c.codigo and l.data is not None
    ]
    if ano is not None:
        lanc = [l for l in lanc if l.data.year == ano]
    if mes is not None:
        lanc = [l for l in lanc if l.data.month == mes]

    operacionais = [l for l in lanc if l.natureza != "transferencia"]
    transferencias = [l for l in lanc if l.natureza == "transferencia"]

    entradas = sum(l.entrada for l in operacionais)
    saidas = sum(l.saida for l in operacionais)
    transf_entrada = sum(l.entrada for l in transferencias)
    transf_saida = sum(l.saida for l in transferencias)

    periodo = _rotulo_periodo(mes, ano)
    por_categoria: dict[str, float] = {}
    for l in operacionais:
        if l.saida > 0:
            d = (l.descricao or "?").strip().upper()
            por_categoria[d] = por_categoria.get(d, 0.0) + l.saida

    res = Resultado(
        titulo=f"{c.rotulo} em {periodo}",
        resumo=(
            f"No {c.rotulo}, em {periodo}: entraram {nz.moeda(entradas)} e "
            f"saíram {nz.moeda(saidas)} em movimento operacional. "
            f"Transferências entre contas do escritório somaram "
            f"{nz.moeda(transf_entrada)} recebidos e {nz.moeda(transf_saida)} "
            f"enviados, e não contam como receita nem despesa."
        ),
        numeros={
            "entradas": entradas,
            "saidas": saidas,
            "resultado": entradas - saidas,
            "transferencias_recebidas": transf_entrada,
            "transferencias_enviadas": transf_saida,
        },
        fonte=[sch.ARQ_FLUXO],
    )
    res.linhas = [
        Linha(cat, valor, "saída por categoria")
        for cat, valor in sorted(por_categoria.items(), key=lambda x: -x[1])[:15]
    ]
    if not c.ativa:
        res.avisos.append(
            f"O {c.rotulo} está marcado como conta inativa. {c.observacao}"
        )
    if c.aba in sch.ABAS_COMPARTILHADAS:
        vizinhas = sorted(
            x.rotulo
            for x in sch.CONTAS.values()
            if x.aba == c.aba and x.codigo != c.codigo
        )
        res.avisos.append(
            f"Os lançamentos do {c.rotulo} moram na aba {c.aba}, junto com "
            f"{' e '.join(vizinhas)}. Separei pela coluna Banco, então este "
            f"número é só do {c.rotulo}."
        )
    if c.codigo == "itau":
        res.avisos.append(
            "O Itaú tem controle concentrado nas entradas. As saídas não são "
            "integralmente lançadas nessa aba, então o resultado acima não é "
            "o saldo da conta."
        )
    return res


# ---------------------------------------------------------------------------
# 8. Despesas por cliente / centro de custo
# ---------------------------------------------------------------------------


def despesas_por_contrato(
    ix: Indice,
    cliente: Optional[str] = None,
    mes: Optional[int] = None,
    ano: Optional[int] = 2026,
    **_: Any,
) -> Resultado:
    """Quanto saiu com um cliente ou centro de custo, em todas as contas."""
    if not cliente:
        return Resultado(
            titulo="Despesas por cliente",
            resumo="",
            faltou="De qual cliente ou centro de custo?",
        )

    lanc = [
        l
        for l in _lancamentos(ix)
        if l.saida > 0
        and l.natureza not in ("transferencia",)
        and l.data is not None
        and nz.cliente_bate(cliente, l.contrato)
    ]
    if ano is not None:
        lanc = [l for l in lanc if l.data.year == ano]
    if mes is not None:
        lanc = [l for l in lanc if l.data.month == mes]

    if not lanc:
        return Resultado(
            titulo="Despesas por cliente",
            resumo=f"Não encontrei saída com o contrato '{cliente}' no período.",
        )

    total = sum(l.saida for l in lanc)
    adiantado = sum(l.saida for l in lanc if l.natureza == "adiantamento")
    custo = total - adiantado
    periodo = _rotulo_periodo(mes, ano)

    por_categoria: dict[str, float] = {}
    for l in lanc:
        d = (l.descricao or "?").strip().upper()
        por_categoria[d] = por_categoria.get(d, 0.0) + l.saida

    res = Resultado(
        titulo=f"Saídas com {cliente} em {periodo}",
        resumo=(
            f"Saíram {nz.moeda(total)} vinculados a '{cliente}' em {periodo}. "
            f"Desse total, {nz.moeda(adiantado)} foram adiantamentos "
            f"reembolsáveis (guias, depósitos, acordos) e {nz.moeda(custo)} "
            f"foram custo do escritório."
        ),
        numeros={"total": total, "adiantado": adiantado, "custo": custo},
        fonte=[sch.ARQ_FLUXO],
    )
    res.linhas = [
        Linha(cat, valor)
        for cat, valor in sorted(por_categoria.items(), key=lambda x: -x[1])[:20]
    ]
    res.avisos.append(
        "Adiantamento não é custo: é dinheiro do escritório que volta por "
        "reembolso. Por isso somei separado."
    )
    return res


# ---------------------------------------------------------------------------
# 9. Margem por cliente
# ---------------------------------------------------------------------------


def margem_cliente(
    ix: Indice,
    cliente: Optional[str] = None,
    ano: Optional[int] = 2026,
    **_: Any,
) -> Resultado:
    """Receita liquida menos custo direto identificado, por cliente.

    E o mais proximo de uma "DRE por area" que os arquivos permitem hoje:
    o modelo do BMG usa volume de atos e alocacao de pessoas, que nao existem
    para os demais clientes. Ver pergunta 8 do mapeamento.
    """
    if not cliente:
        return Resultado(
            titulo="Margem por cliente",
            resumo="",
            faltou="De qual cliente?",
        )

    notas = [
        n
        for n in ix.notas
        if not n.bloco_secundario
        and n.emitida
        and n.ano == ano
        and nz.cliente_bate(cliente, n.cliente)
    ]
    lanc = [
        l
        for l in _lancamentos(ix)
        if l.saida > 0
        and l.natureza not in ("transferencia", "adiantamento")
        and l.data is not None
        and l.data.year == ano
        and nz.cliente_bate(cliente, l.contrato)
    ]

    if not notas and not lanc:
        return Resultado(
            titulo="Margem por cliente",
            resumo=f"Não encontrei receita nem despesa para '{cliente}' em {ano}.",
        )

    receita = sum(n.valor for n in notas)
    custo = sum(l.saida for l in lanc)
    margem = receita - custo
    pct = (margem / receita * 100) if receita else 0.0

    res = Resultado(
        titulo=f"Margem de {cliente} em {ano}",
        resumo=(
            f"Receita líquida faturada de {nz.moeda(receita)} contra "
            f"{nz.moeda(custo)} de custo direto identificado nos razões. "
            f"Margem de {nz.moeda(margem)} ({pct:.1f}%)."
        ),
        numeros={
            "receita": receita,
            "custo_direto": custo,
            "margem": margem,
            "margem_pct": pct,
        },
        fonte=[sch.ARQ_FLUXO] + sorted({_origem_nota(n).split(" > ")[0] for n in notas}),
    )
    res.linhas = [
        Linha("Receita líquida faturada", receita, f"{len(notas)} notas"),
        Linha("Custo direto identificado", -custo, f"{len(lanc)} lançamentos"),
        Linha("Margem", margem, f"{pct:.1f}%"),
    ]
    res.avisos.append(
        "Custo direto é o que está lançado com esse contrato nos razões. Não "
        "inclui rateio de estrutura, folha da controladoria nem imposto, "
        "porque a planilha não tem essa alocação fora do BMG. Este número não "
        "é comparável com a DRE do BMG, que trabalha por volume de atos."
    )
    return res


# ---------------------------------------------------------------------------
# 10. Posicao geral
# ---------------------------------------------------------------------------


def posicao_geral(ix: Indice, ano: Optional[int] = 2026, **_: Any) -> Resultado:
    """Panorama: faturado, recebido, a receber e reembolsos em aberto."""
    fat = faturamento(ix, mes=None, ano=ano)
    reemb = reembolsos_pendentes(ix)

    hoje = dt.date.today()
    mes_atual = recebimentos(ix, mes=hoje.month, ano=hoje.year)

    res = Resultado(
        titulo=f"Posição geral de {ano}",
        resumo=(
            f"Faturado {nz.moeda(fat.numeros['faturado'])} em {ano}, com "
            f"{nz.moeda(fat.numeros['recebido'])} recebidos. Em aberto: "
            f"{nz.moeda(fat.numeros['pendente'])} marcados PENDENTE e "
            f"{nz.moeda(reemb.numeros['total'])} de reembolsos."
        ),
        numeros={**fat.numeros, "reembolsos_abertos": reemb.numeros["total"]},
        fonte=sorted(set(fat.fonte + reemb.fonte)),
    )
    res.linhas = [
        Linha("Faturado no ano", fat.numeros["faturado"]),
        Linha("Recebido no ano", fat.numeros["recebido"]),
        Linha("A receber, marcado PENDENTE", fat.numeros["pendente"]),
        Linha("A receber, sem baixa registrada", fat.numeros["sem_baixa"]),
        Linha("Previsto, nota não emitida", fat.numeros["previsto"]),
        Linha("Reembolsos em aberto", reemb.numeros["total"]),
        Linha(
            f"Recebido em {nz.rotulo_mes(hoje.month, hoje.year)}",
            mes_atual.numeros["recebido"],
        ),
    ]
    res.avisos = fat.avisos
    return res


# ---------------------------------------------------------------------------
# 11. Notas de um mes (listagem)
# ---------------------------------------------------------------------------


def listar_notas(
    ix: Indice,
    mes: Optional[int] = None,
    ano: Optional[int] = 2026,
    entidade: Optional[str] = None,
    estado: Optional[str] = None,
    **_: Any,
) -> Resultado:
    """Lista as notas de um periodo, opcionalmente filtradas por estado."""
    codigo = _resolver_entidade(entidade)
    notas = _notas_do_periodo(ix, mes, ano, codigo)
    if estado:
        alvo = nz.chave(estado)
        mapa = {
            "recebida": ESTADO_RECEBIDA,
            "recebidas": ESTADO_RECEBIDA,
            "pendente": ESTADO_PENDENTE,
            "pendentes": ESTADO_PENDENTE,
            "prevista": ESTADO_PREVISTA,
            "previstas": ESTADO_PREVISTA,
        }
        if alvo in mapa:
            notas = [n for n in notas if n.estado == mapa[alvo]]

    periodo = _rotulo_periodo(mes, ano)
    res = Resultado(
        titulo=f"Notas de {periodo}",
        resumo=(
            f"{len(notas)} linhas em {periodo}, somando "
            f"{nz.moeda(sum(n.valor for n in notas))} líquidos."
        ),
        numeros={"total": sum(n.valor for n in notas)},
        fonte=sorted({_origem_nota(n).split(' > ')[0] for n in notas}),
    )
    for n in sorted(notas, key=lambda x: (x.entidade, x.linha)):
        res.linhas.append(
            Linha(
                rotulo=f"NF {n.numero or '(sem NF)'} - {n.cliente}",
                valor=n.valor,
                detalhe=n.observacoes,
                origem=_origem_nota(n),
                estado=ROTULO_ESTADO.get(n.estado),
            )
        )
    return res


# ---------------------------------------------------------------------------
# Catalogo
#
# O que o modelo de linguagem pode pedir. Cada entrada declara os parametros
# aceitos; qualquer coisa fora disso e ignorada.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Consulta:
    nome: str
    funcao: Callable[..., Resultado]
    descricao: str
    parametros: dict[str, str]
    exemplos: tuple[str, ...]


CATALOGO: dict[str, Consulta] = {
    "faturamento": Consulta(
        nome="faturamento",
        funcao=faturamento,
        descricao=(
            "Quanto foi faturado num periodo, pela data de emissao, separando "
            "recebido, em aberto e previsto."
        ),
        parametros={
            "mes": "numero do mes 1-12, opcional",
            "ano": "ano, padrao 2026",
            "entidade": "principal ou rafaela, opcional",
        },
        exemplos=("Quanto faturamos em julho?", "Quanto a Rafaela faturou em maio?"),
    ),
    "recebimentos": Consulta(
        nome="recebimentos",
        funcao=recebimentos,
        descricao="Quanto entrou de fato num periodo, pela data de recebimento.",
        parametros={
            "mes": "numero do mes 1-12",
            "ano": "ano, padrao 2026",
            "entidade": "principal ou rafaela, opcional",
        },
        exemplos=("Quanto recebemos este mes?", "Quanto entrou em junho?"),
    ),
    "a_receber": Consulta(
        nome="a_receber",
        funcao=a_receber,
        descricao="Notas emitidas que ainda nao foram recebidas.",
        parametros={
            "cliente": "nome do cliente, opcional",
            "entidade": "principal ou rafaela, opcional",
        },
        exemplos=("Quanto temos para receber?", "O que a FFST ainda deve?"),
    ),
    "cliente_posicao": Consulta(
        nome="cliente_posicao",
        funcao=cliente_posicao,
        descricao="Quanto um cliente deve, somando notas em aberto e notas de debito.",
        parametros={"cliente": "nome do cliente, obrigatorio"},
        exemplos=("Quanto o BMG nos deve?", "Qual a posicao da Flapa?"),
    ),
    "reembolsos_pendentes": Consulta(
        nome="reembolsos_pendentes",
        funcao=reembolsos_pendentes,
        descricao=(
            "Reembolsos em aberto nas tres trilhas: lotes de guias do BMG, "
            "reembolsos manuais por processo e notas de debito."
        ),
        parametros={},
        exemplos=(
            "Quais reembolsos estao pendentes?",
            "Quanto o BMG ainda precisa reembolsar?",
        ),
    ),
    "guias_adiantadas": Consulta(
        nome="guias_adiantadas",
        funcao=guias_adiantadas,
        descricao="Quanto o escritorio adiantou em guias e depositos no periodo.",
        parametros={"mes": "numero do mes 1-12", "ano": "ano, padrao 2026"},
        exemplos=("Quanto adiantamos em guias este mes?",),
    ),
    "guias_sem_lote": Consulta(
        nome="guias_sem_lote",
        funcao=guias_sem_lote,
        descricao="Guias pagas que ainda nao entraram em nenhum lote de cobranca.",
        parametros={},
        exemplos=("Quais guias pagamos e ainda nao foram cobradas?",),
    ),
    "movimento_conta": Consulta(
        nome="movimento_conta",
        funcao=movimento_conta,
        descricao=(
            "Entradas e saidas de uma conta bancaria no periodo, separando "
            "transferencia entre contas do proprio escritorio."
        ),
        parametros={
            "conta": "itau, inter, inter2, inter3, santander ou omie_cash",
            "mes": "numero do mes 1-12",
            "ano": "ano, padrao 2026",
        },
        exemplos=(
            "Quanto saiu do Santander este mes?",
            "Quanto a Omie Cash pagou em julho?",
        ),
    ),
    "despesas_por_contrato": Consulta(
        nome="despesas_por_contrato",
        funcao=despesas_por_contrato,
        descricao="Quanto saiu vinculado a um cliente ou centro de custo.",
        parametros={
            "cliente": "nome do cliente ou centro de custo",
            "mes": "numero do mes 1-12",
            "ano": "ano, padrao 2026",
        },
        exemplos=("Quanto gastamos com o BMG em julho?",),
    ),
    "margem_cliente": Consulta(
        nome="margem_cliente",
        funcao=margem_cliente,
        descricao=(
            "Receita liquida menos custo direto identificado, por cliente. "
            "E a visao mais proxima de DRE por area que os arquivos permitem."
        ),
        parametros={"cliente": "nome do cliente", "ano": "ano, padrao 2026"},
        exemplos=("Qual a margem da ARG?", "Me mostre a DRE da FFST."),
    ),
    "posicao_geral": Consulta(
        nome="posicao_geral",
        funcao=posicao_geral,
        descricao="Panorama do ano: faturado, recebido, a receber e reembolsos.",
        parametros={"ano": "ano, padrao 2026"},
        exemplos=("Como estamos?", "Me da um resumo geral."),
    ),
    "listar_notas": Consulta(
        nome="listar_notas",
        funcao=listar_notas,
        descricao="Lista as notas de um periodo, com estado de cada uma.",
        parametros={
            "mes": "numero do mes 1-12",
            "ano": "ano, padrao 2026",
            "entidade": "principal ou rafaela, opcional",
            "estado": "recebida, pendente ou prevista, opcional",
        },
        exemplos=("Lista as notas de agosto.",),
    ),
}


def executar(ix: Indice, nome: str, parametros: dict[str, Any]) -> Resultado:
    """Executa uma consulta do catalogo. Erra alto se o nome nao existir."""
    consulta = CATALOGO.get(nome)
    if consulta is None:
        raise KeyError(f"Consulta desconhecida: {nome}")
    limpos = {k: v for k, v in parametros.items() if k in consulta.parametros}
    return consulta.funcao(ix, **limpos)
