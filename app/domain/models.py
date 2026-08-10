# -*- coding: utf-8 -*-
"""Modelo de dominio.

Objetos imutaveis que representam o que as planilhas ja registram. Nenhum
conceito novo foi inventado aqui: cada campo tem origem numa coluna real,
apontada em schema.py.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

# ---------------------------------------------------------------------------
# Faturamento
# ---------------------------------------------------------------------------

# Estados possiveis de uma linha de faturamento:
#
#   A (NF) vazia ou "X"          -> prevista   (nota nao emitida)
#   G data                       -> recebida
#   G "PENDENTE"                 -> pendente   (faturada, cobranca em aberto)
#   G vazia + obs de cancelamento-> cancelada  (nota anulada, muitas vezes
#                                               substituida por outra NF)
#   G vazia e mais nada          -> sem_baixa  (nao sabemos o que houve)
#
# Sobre "cancelada": as 25 notas de janeiro a junho com a coluna G vazia
# trazem, TODAS, marca de cancelamento na observacao ("cancelada",
# "cancelada/nova NF 111/2026", "erro de emissao", "substituida"). Nao sao
# cobranca viva nem baixa esquecida: sao notas anuladas. Confirmado com o
# escritorio em agosto de 2026, e conferido no arquivo - nenhuma nota recebida
# menciona cancelamento, e nenhuma PENDENTE tambem.
#
# Nota cancelada nao e receita: fica fora de faturado E de contas a receber.
ESTADO_PREVISTA = "prevista"
ESTADO_PENDENTE = "pendente"
ESTADO_CANCELADA = "cancelada"
ESTADO_SEM_BAIXA = "sem_baixa"
ESTADO_RECEBIDA = "recebida"

ESTADOS_EM_ABERTO = (ESTADO_PENDENTE, ESTADO_SEM_BAIXA)

# Marcas que, na observacao de uma nota sem data de recebimento, indicam que
# ela foi anulada. Sem acento: a comparacao normaliza antes.
MARCAS_DE_CANCELAMENTO = (
    "cancel",
    "erro de emiss",
    "substitu",
    "nao faturar",
    "nao emitir",
    "duplicid",
)

# Textos que aparecem na coluna da NF significando "nao emitida".
NF_NAO_EMITIDA = {"X", "XX", "-", "--"}


@dataclass(frozen=True)
class Nota:
    """Uma linha de aba mensal de faturamento."""

    entidade: str  # "principal" | "rafaela"
    aba: str  # nome literal da aba, com espacos como no arquivo
    linha: int  # linha real na planilha (1-based)
    numero: Optional[str]  # coluna A
    cliente: Optional[str]  # coluna B
    valor_bruto: Optional[float]  # coluna C
    valor_liquido: Optional[float]  # coluna D
    referencia: Optional[str]  # coluna E - competencia
    observacoes: Optional[str]  # coluna F
    data_recebimento: Optional[dt.date]  # coluna G, quando e data
    marcador_pendente: bool  # coluna G contem "PENDENTE"
    nota_livre: Optional[str]  # coluna H
    mes: int
    ano: int
    bloco_secundario: bool = False  # linha fora do bloco principal da aba

    @property
    def cancelada(self) -> bool:
        """Nota anulada: sem recebimento e com marca de cancelamento na obs.

        A data de recebimento manda: se o dinheiro entrou, a nota valeu,
        qualquer que seja o texto da observacao.
        """
        if self.data_recebimento is not None:
            return False
        texto = f"{self.observacoes or ''} {self.nota_livre or ''}"
        alvo = _sem_acento(texto).lower()
        return any(m in alvo for m in MARCAS_DE_CANCELAMENTO)

    @property
    def estado(self) -> str:
        if not self.numero or self.numero.strip().upper() in NF_NAO_EMITIDA:
            return ESTADO_PREVISTA
        if self.data_recebimento is not None:
            return ESTADO_RECEBIDA
        if self.marcador_pendente:
            return ESTADO_PENDENTE
        if self.cancelada:
            return ESTADO_CANCELADA
        return ESTADO_SEM_BAIXA

    @property
    def valor(self) -> float:
        """Valor liquido, que e o que circula no caixa."""
        if self.valor_liquido is not None:
            return self.valor_liquido
        return self.valor_bruto or 0.0

    @property
    def emitida(self) -> bool:
        """Nota que existe e vale. Cancelada nao conta como faturamento."""
        return self.estado in (
            ESTADO_RECEBIDA, ESTADO_PENDENTE, ESTADO_SEM_BAIXA
        )

    @property
    def em_aberto(self) -> bool:
        return self.estado in ESTADOS_EM_ABERTO


# ---------------------------------------------------------------------------
# Razoes bancarios
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Lancamento:
    """Uma linha de razao bancario.

    Cuidado com a diferenca entre 'conta' e 'conta_efetiva': a aba diz onde a
    linha mora, a coluna BANCO diz de qual conta o dinheiro saiu. Na aba
    SANTANDER convivem Santander, Omie Cash e Inter 3. Consulta sobre conta
    usa sempre conta_efetiva.
    """

    conta: str  # conta dona da aba onde a linha esta
    aba: str
    linha: int
    remetente: Optional[str]
    contrato: Optional[str]  # cliente / centro de custo
    descricao: Optional[str]  # categoria livre, vocabulario por conta
    saida: float
    entrada: float
    data: Optional[dt.date]
    banco: Optional[str]
    historico: Optional[str]
    rotulo_reembolso: Optional[str]  # lote (REEMBOLSO 12) ou ND (ND 02/2026)
    natureza: str  # ver schema.classificar_descricao
    conta_efetiva: str = ""  # conta que de fato moveu, lida da coluna BANCO
    # True quando a linha esta numa aba que nao e a da sua conta e a conta tem
    # aba propria: e copia de um lancamento que ja existe la. Nao entra em
    # total nenhum. Ver schema.e_espelho.
    espelho: bool = False

    @property
    def valor_liquido(self) -> float:
        return self.entrada - self.saida

    @property
    def e_entrada(self) -> bool:
        return self.entrada > 0


# ---------------------------------------------------------------------------
# Reembolsos - trilha A: lotes de guias judiciais
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoteReembolso:
    ano: int
    aba: str
    linha: int
    status: Optional[str]
    valor: float
    data_recebimento: Optional[dt.date]
    descricao: Optional[str]  # "REEMBOLSO 55/26 - 29/07/2026 A 30/07/2026"
    numero_lote: Optional[str]  # "55/26", extraido da descricao
    pendente: bool
    quitado: bool


# ---------------------------------------------------------------------------
# Reembolsos - trilha B: manuais por processo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReembolsoManual:
    aba: str
    linha: int
    status: Optional[str]
    valor: float
    data_recebimento: Optional[dt.date]
    parte: Optional[str]
    civ: Optional[str]  # numero do processo
    chamado: Optional[str]  # #REQ-...
    observacao: Optional[str]
    ano_origem: Optional[str]
    pendente: bool
    # True quando veio da aba viva (GUIAS 2026), que consolida as pendencias
    # de todos os anos. Apenas essas alimentam totais - ver schema.AbaGuias.
    consolidado: bool = True

    @property
    def ano_pendencia(self) -> Optional[int]:
        """Extrai o ano do status ("PENDENTE 2024" -> 2024)."""
        if not self.status:
            return None
        for token in self.status.split():
            if token.isdigit() and len(token) == 4:
                return int(token)
        return None


# ---------------------------------------------------------------------------
# Reembolsos - trilha C: notas de debito
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NotaDebito:
    aba: str
    linha: int
    numero: Optional[str]  # "17/2026"
    responsavel: Optional[str]
    cliente: Optional[str]
    data_envio: Optional[dt.date]
    valor: Optional[float]
    data_pagamento: Optional[dt.date]
    texto_pagamento: Optional[str]  # quando G nao e data ("nao recebemos")
    despesas: Optional[str]

    @property
    def quitada(self) -> bool:
        return self.data_pagamento is not None

    @property
    def em_aberto(self) -> bool:
        return self.valor is not None and self.data_pagamento is None


# ---------------------------------------------------------------------------
# Avisos de integridade
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Aviso:
    """Anomalia encontrada na leitura, exposta junto com a resposta.

    Existe porque o sistema nunca deve dar um numero limpo escondendo que a
    fonte tem problema. Cada aviso aponta arquivo, aba e o que houve.
    """

    severidade: str  # "info" | "atencao" | "critico"
    arquivo: str
    aba: Optional[str]
    mensagem: str


@dataclass
class Indice:
    """Tudo que foi lido dos arquivos, ja normalizado."""

    notas: list[Nota] = field(default_factory=list)
    lancamentos: list[Lancamento] = field(default_factory=list)
    lotes: list[LoteReembolso] = field(default_factory=list)
    manuais: list[ReembolsoManual] = field(default_factory=list)
    notas_debito: list[NotaDebito] = field(default_factory=list)
    avisos: list[Aviso] = field(default_factory=list)
    mapa_cnpj: dict[str, str] = field(default_factory=dict)
    carregado_em: Optional[dt.datetime] = None
    arquivos_lidos: dict[str, str] = field(default_factory=dict)
