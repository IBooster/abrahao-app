# -*- coding: utf-8 -*-
"""
MAPA DECLARATIVO DAS PLANILHAS.

Este arquivo e a unica fonte de verdade sobre ONDE cada dado mora.
Foi derivado da leitura completa dos 5 arquivos (Fase 1), nao de suposicao.

Regra do projeto: nenhuma decisao de posicao (arquivo, aba, coluna, linha)
pode existir fora deste modulo. O modelo de linguagem nunca ve um endereco
de celula; ele produz uma intencao tipada e o codigo resolve a posicao aqui.

Toda alteracao neste arquivo e uma mudanca de contrato com as planilhas reais
e precisa ser revisada como tal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Arquivos
# ---------------------------------------------------------------------------

ARQ_FLUXO = "Fluxo de caixa_Abrahao Advogados_2026.xlsx"
ARQ_FAT_PRINCIPAL = (
    "Faturamento 2026 - ABRAHAO SOCIEDADE DE ADVOGADOS (31.591.483.0001-70).xlsx"
)
ARQ_FAT_RAFAELA = (
    "Faturamento 2026 - RAFAELA ABRAHAO SOCIEDADE DE ADVOGADOS (66.325.087.0001-85).xlsx"
)
ARQ_REEMBOLSOS = "FECHAMENTO REEMBOLSOS.xlsx"
ARQ_DRE_BMG = "DRE BMG - Julho 2026.xlsx"

ARQUIVOS_ESPERADOS = [
    ARQ_FLUXO,
    ARQ_FAT_PRINCIPAL,
    ARQ_FAT_RAFAELA,
    ARQ_REEMBOLSOS,
    ARQ_DRE_BMG,
]

# Como cada arquivo se apresenta para quem vai envia-lo, e o que precisa ter
# dentro para ser aceito. Um arquivo que nao traga estas abas nao e o arquivo
# que dizem que e, e o upload recusa antes de substituir o que ja existe.
@dataclass(frozen=True)
class ArquivoEsperado:
    nome: str
    rotulo: str
    descricao: str
    abas_obrigatorias: tuple[str, ...]


ARQUIVOS: dict[str, ArquivoEsperado] = {
    ARQ_FLUXO: ArquivoEsperado(
        nome=ARQ_FLUXO,
        rotulo="Fluxo de caixa",
        descricao="Razao de cada conta, matriz mensal e controle de notas de debito.",
        abas_obrigatorias=("ITAU", "INTER", "SANTANDER", "REEMBOLSO", "2026"),
    ),
    ARQ_FAT_PRINCIPAL: ArquivoEsperado(
        nome=ARQ_FAT_PRINCIPAL,
        rotulo="Faturamento - CNPJ principal",
        descricao="Notas emitidas e recebidas pela sociedade principal.",
        abas_obrigatorias=("NOTAS",),
    ),
    ARQ_FAT_RAFAELA: ArquivoEsperado(
        nome=ARQ_FAT_RAFAELA,
        rotulo="Faturamento - CNPJ Rafaela",
        descricao="Notas emitidas e recebidas pela sociedade individual.",
        abas_obrigatorias=("NOTAS",),
    ),
    ARQ_REEMBOLSOS: ArquivoEsperado(
        nome=ARQ_REEMBOLSOS,
        rotulo="Fechamento de reembolsos",
        descricao="Lotes de guias do BMG e reembolsos manuais por processo.",
        abas_obrigatorias=("GUIAS 2026",),
    ),
    ARQ_DRE_BMG: ArquivoEsperado(
        nome=ARQ_DRE_BMG,
        rotulo="DRE BMG",
        descricao="Modelo de rentabilidade das equipes do BMG.",
        abas_obrigatorias=("GERAL",),
    ),
}

# Subpastas de apoio dentro da pasta das planilhas. Nunca sao lidas como dado.
PASTA_BACKUPS = "_backups"
PASTA_AUDITORIA = "_auditoria"


# ---------------------------------------------------------------------------
# CNPJs / entidades faturadoras
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Entidade:
    codigo: str
    nome: str
    cnpj: str
    arquivo: str
    regime: str
    emissao: str
    apelidos: tuple[str, ...]


ENTIDADES: dict[str, Entidade] = {
    "principal": Entidade(
        codigo="principal",
        nome="Abrahao Sociedade de Advogados",
        cnpj="31.591.483/0001-70",
        arquivo=ARQ_FAT_PRINCIPAL,
        regime="Lucro Presumido",
        emissao="Omie",
        apelidos=("principal", "matriz", "sociedade principal", "abrahao", "31591483"),
    ),
    "rafaela": Entidade(
        codigo="rafaela",
        nome="Rafaela Abrahao Sociedade Individual de Advocacia",
        cnpj="66.325.087/0001-85",
        arquivo=ARQ_FAT_RAFAELA,
        regime="Simples Nacional",
        emissao="Portal da Prefeitura",
        apelidos=(
            "rafaela",
            "individual",
            "sociedade individual",
            "simples",
            "novo cnpj",
            "66325087",
        ),
    ),
}


# ---------------------------------------------------------------------------
# Abas mensais de faturamento
# ---------------------------------------------------------------------------

MESES = [
    "janeiro",
    "fevereiro",
    "marco",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]

# Como o mes aparece no nome da aba (com acento, como esta no arquivo real).
MES_ABA = {
    1: "janeiro",
    2: "fevereiro",
    3: "março",
    4: "abril",
    5: "maio",
    6: "junho",
    7: "julho",
    8: "agosto",
    9: "setembro",
    10: "outubro",
    11: "novembro",
    12: "dezembro",
}

# Abas que existem nos arquivos de faturamento mas NAO sao meses.
FAT_ABAS_NAO_MENSAIS = {"NOTAS", "levantamento notas"}


@dataclass(frozen=True)
class ColunasFaturamento:
    """Layout das abas mensais. Identico nos dois CNPJs."""

    linha_cabecalho: int = 1
    primeira_linha: int = 2
    nf: int = 1  # A
    cliente: int = 2  # B
    valor_bruto: int = 3  # C
    valor_liquido: int = 4  # D
    referencia: int = 5  # E  (competencia)
    observacoes: int = 6  # F
    data_recebimento: int = 7  # G
    nota_livre: int = 8  # H


COLS_FAT = ColunasFaturamento()

# Marcador textual usado na coluna G para "faturado, nao recebido".
# Aparece no arquivo real com espaco no fim ("PENDENTE ") - normalizar sempre.
MARCADOR_PENDENTE = "PENDENTE"


# ---------------------------------------------------------------------------
# Razoes bancarios (abas do fluxo de caixa)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Conta:
    codigo: str
    aba: str  # onde a linha mora fisicamente
    rotulo: str
    # Valores da coluna BANCO que identificam esta conta. Uma aba pode abrigar
    # mais de uma conta: a aba SANTANDER guarda tambem Omie Cash e Inter 3,
    # separados apenas por essa coluna. Confirmado pelo financeiro em 08/2026.
    marcadores: tuple[str, ...]
    # posicoes de coluna (1-based)
    remetente: int
    contrato: int
    descricao: int
    saida: int
    entrada: int
    data: int
    banco: int
    historico: int
    reembolso: Optional[int]  # coluna de rotulo de lote / ND; None quando nao existe
    nome_col_data: str
    ativa: bool
    observacao: str
    apelidos: tuple[str, ...] = field(default_factory=tuple)


CONTAS: dict[str, Conta] = {
    "itau": Conta(
        codigo="itau",
        aba="ITAU",
        rotulo="Itaú",
        marcadores=("ITAU", "ITAÚ"),
        remetente=1,
        contrato=2,
        descricao=3,
        saida=4,
        entrada=5,
        data=6,
        banco=7,
        historico=8,
        reembolso=None,
        nome_col_data="VENCIMENTO",
        ativa=True,
        observacao=(
            "Controle concentrado nas ENTRADAS. Recebe faturamento e reembolso de "
            "guias do BMG. As saidas nao sao integralmente controladas nesta aba."
        ),
        apelidos=("itau", "itaú"),
    ),
    "inter": Conta(
        codigo="inter",
        aba="INTER",
        rotulo="Inter 1",
        marcadores=("INTER", "ESPECIE", "ESPÉCIE"),
        remetente=1,
        contrato=2,
        descricao=3,
        saida=4,
        entrada=5,
        data=6,
        banco=7,
        historico=9,
        reembolso=8,
        nome_col_data="DATA",
        ativa=True,
        observacao=(
            "Conta das guias judiciais. A coluna REEMBOLSO carrega o rotulo do lote "
            "(REEMBOLSO 01 .. REEMBOLSO 56) que amarra a guia ao fechamento."
        ),
        apelidos=("inter", "inter 1", "inter1"),
    ),
    "inter2": Conta(
        codigo="inter2",
        aba="INTER (2)",
        rotulo="Inter 2",
        marcadores=("INTER 2", "INTER2"),
        remetente=1,
        contrato=2,
        descricao=3,
        saida=4,
        entrada=5,
        data=6,
        banco=7,
        historico=9,
        reembolso=8,
        nome_col_data="DATA",
        ativa=False,
        observacao=(
            "Declarada inativa pelo escritorio, mas contem lancamentos de condenacao "
            "ate 02/06/2026. Pergunta 3 do mapeamento, em aberto. Somente leitura."
        ),
        apelidos=("inter 2", "inter2"),
    ),
    "inter3": Conta(
        codigo="inter3",
        aba="INTER (3)",
        rotulo="Inter 3",
        marcadores=("INTER 3", "INTER3"),
        remetente=1,
        contrato=2,
        descricao=3,
        saida=4,
        entrada=5,
        data=6,
        banco=7,
        historico=9,
        reembolso=8,
        nome_col_data="DATA",
        ativa=True,
        observacao=(
            "Conta do CNPJ Rafaela. Recebe faturamento desse CNPJ e paga despesas."
        ),
        apelidos=("inter 3", "inter3", "rafaela"),
    ),
    "santander": Conta(
        codigo="santander",
        aba="SANTANDER",
        rotulo="Santander",
        marcadores=("SANTANDER",),
        remetente=1,
        contrato=2,
        descricao=3,
        saida=4,
        entrada=5,
        data=6,
        banco=7,
        historico=9,
        reembolso=8,
        nome_col_data="VENCIMENTO",
        ativa=True,
        observacao=(
            "Conta operacional. Concentra folha, impostos e despesas correntes. "
            "A coluna REEMBOLSO carrega o numero da nota de debito (ND 02/2026). "
            "A aba abriga tambem Omie Cash e Inter 3, separados pela coluna BANCO."
        ),
        apelidos=("santander",),
    ),
    "omie_cash": Conta(
        codigo="omie_cash",
        aba="SANTANDER",
        rotulo="Omie Cash",
        marcadores=("OMIE CASH", "OMIE ACASH", "OMIECASH"),
        remetente=1,
        contrato=2,
        descricao=3,
        saida=4,
        entrada=5,
        data=6,
        banco=7,
        historico=9,
        reembolso=8,
        nome_col_data="VENCIMENTO",
        ativa=True,
        observacao=(
            "Nao tem aba propria. Mora dentro da aba SANTANDER e e identificada "
            "pela coluna BANCO. Confirmado pelo financeiro em agosto de 2026. "
            "Recebe aporte de outras contas e paga despesas do escritorio."
        ),
        apelidos=("omie cash", "omiecash", "omie acash", "omie", "cash"),
    ),
}

# Abas que abrigam mais de uma conta. A coluna BANCO e quem separa.
ABAS_COMPARTILHADAS = {"SANTANDER"}


def conta_efetiva(aba: str, banco: str | None, conta_da_aba: str) -> str:
    """Decide de qual conta o dinheiro saiu ou entrou.

    A coluna BANCO so desempata nas abas que abrigam mais de uma conta - hoje
    apenas SANTANDER, onde convivem Santander, Omie Cash e Inter 3.

    Nas demais, a aba manda. As abas INTER (2) e INTER (3) trazem "INTER" na
    coluna BANCO, generico, e obedecer a esse texto jogaria os lancamentos
    delas para o Inter 1.
    """
    if aba not in ABAS_COMPARTILHADAS or not banco:
        return conta_da_aba
    alvo = " ".join(str(banco).strip().upper().split())
    for conta in CONTAS.values():
        if alvo in conta.marcadores:
            return conta.codigo
    return conta_da_aba


def e_espelho(aba: str, codigo_conta_efetiva: str) -> bool:
    """Diz se a linha e copia de um lancamento que ja existe em outra aba.

    A aba SANTANDER traz 98 linhas marcadas como Inter 3, e 87 delas repetem,
    com mesma data, valor e contraparte, linhas que ja estao na aba
    INTER (3) - R$ 187.994,52 de R$ 188.009,96. Somar as duas dobraria o
    movimento da conta.

    O criterio e estrutural, nao uma lista de casos: se a conta tem aba
    propria e a linha esta em outra aba, ela e copia. A Omie Cash nao cai
    aqui porque a aba SANTANDER e a casa dela, nao ha outra.
    """
    conta = CONTAS.get(codigo_conta_efetiva)
    if conta is None:
        return False
    return conta.aba != aba


# ---------------------------------------------------------------------------
# Vocabulario da coluna DESCRICAO
#
# Cada conta usa um vocabulario proprio. Estes sao os termos que JA EXISTEM nos
# arquivos. Servem para classificar leitura e, na Fase 3, para restringir
# escrita: o sistema nao deve inventar categoria nova.
# ---------------------------------------------------------------------------

# Categorias que representam entrada de caixa por servico prestado.
DESC_FATURAMENTO = {"FATURAMENTO"}

# Categorias que representam reembolso recebido de cliente.
DESC_REEMBOLSO = {"REEMBOLSO"}

# Categorias que representam dinheiro adiantado pelo escritorio em nome do
# cliente - geram reembolso a receber.
DESC_ADIANTAMENTO = {
    "TAXAS JUDICIAIS",
    "DEPOSITO JUDICIAL",
    "DEPÓSITO JUDICIAL",
    "CONDENACAO",
    "CONDENAÇÃO",
    "ACORDO",
}

# Movimento entre contas do proprio escritorio. Nunca e receita nem despesa.
DESC_TRANSFERENCIA = {
    "TRANSFERENCIA ENTRE CONTAS",
    "TRANSFERÊNCIA ENTRE CONTAS",
}

# Resultado financeiro, nao operacional.
DESC_FINANCEIRO = {
    "RENDIMENTO APLICACAO",
    "RENDIMENTO APLICAÇÃO",
    "RESGATE APLICACAO FINANCEIRA",
    "RESGATE APLICAÇÃO FINANCEIRA",
    "APLICACAO CDB/RDB",
    "APLICAÇÃO CDB/RDB",
    "RESGATE CDB DI",
}


def classificar_descricao(descricao: str | None) -> str:
    """Traduz o texto livre da coluna DESCRICAO numa natureza economica.

    Retorna: faturamento | reembolso | adiantamento | transferencia |
             financeiro | despesa
    """
    if not descricao:
        return "despesa"
    d = descricao.strip().upper()
    if d in DESC_TRANSFERENCIA:
        return "transferencia"
    if d in DESC_FATURAMENTO:
        return "faturamento"
    if d in DESC_REEMBOLSO:
        return "reembolso"
    if d in DESC_ADIANTAMENTO:
        return "adiantamento"
    if d in DESC_FINANCEIRO:
        return "financeiro"
    return "despesa"


# ---------------------------------------------------------------------------
# Reembolsos - guias judiciais (FECHAMENTO REEMBOLSOS.xlsx)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AbaGuias:
    aba: str
    ano: int
    # bloco de lotes
    lote_primeira_linha: int
    lote_ultima_linha: int  # onde o bloco de lotes termina (exclusivo)
    lote_status: int
    lote_valor: int
    lote_data: int
    lote_descricao: int
    # bloco de reembolsos manuais (por processo)
    manual_primeira_linha: Optional[int]
    # A aba de 2026 e a lista VIVA de reembolsos manuais: ela repete as
    # pendencias de 2024 e 2025 que ainda nao foram resolvidas. Somar os dois
    # blocos contaria a mesma pendencia duas vezes, entao so a consolidada
    # alimenta totais.
    manuais_consolidados: bool
    manual_linha_cabecalho: Optional[int] = None
    manual_status: int = 1
    manual_valor: int = 2
    manual_recebimento: int = 3
    manual_parte: int = 4
    manual_civ: int = 5
    manual_chamado: int = 6
    manual_observacao: int = 7
    manual_ano: int = 8


GUIAS = {
    2025: AbaGuias(
        aba="GUIAS 2025",
        ano=2025,
        lote_primeira_linha=3,
        lote_ultima_linha=104,
        lote_status=1,
        lote_valor=2,
        lote_data=3,
        lote_descricao=4,
        manual_primeira_linha=104,
        manuais_consolidados=False,
    ),
    2026: AbaGuias(
        aba="GUIAS 2026",
        ano=2026,
        lote_primeira_linha=3,
        lote_ultima_linha=68,
        lote_status=1,
        lote_valor=2,
        lote_data=3,
        lote_descricao=4,
        manual_linha_cabecalho=68,
        manual_primeira_linha=69,
        manuais_consolidados=True,
    ),
}

STATUS_QUITADO = {"OK", "PAGO", "RECEBIDO", "REALIZADO"}


def status_e_pendente(status: str | None) -> bool:
    if not status:
        return False
    return "PENDENTE" in status.strip().upper()


def status_e_quitado(status: str | None) -> bool:
    if not status:
        return False
    return status.strip().upper() in STATUS_QUITADO


# ---------------------------------------------------------------------------
# Notas de debito (Fluxo de caixa > aba REEMBOLSO)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AbaNotasDebito:
    aba: str = "REEMBOLSO"
    linha_cabecalho: int = 7
    primeira_linha: int = 8
    nd: int = 2  # B
    responsavel: int = 3  # C
    cliente: int = 4  # D
    data_envio: int = 5  # E
    valor: int = 6  # F
    data_pagamento: int = 7  # G
    despesas: int = 8  # H


ND = AbaNotasDebito()

# Textos que aparecem na coluna de data de pagamento significando "nao recebido".
ND_NAO_RECEBIDO = ("nao recebemos", "não recebemos", "pendente")


# ---------------------------------------------------------------------------
# Matriz mensal consolidada (Fluxo de caixa > aba 2026)
#
# O financeiro confirmou em agosto de 2026: esta aba e preenchida A MAO, uma
# vez por mes, durante a conciliacao e o fechamento. Nao e alimentada
# lancamento a lancamento, e por isso os valores aparecem concatenados dentro
# da formula (ex.: =32805.24+32058.23+46925).
#
# Consequencias, que valem como regra do sistema:
#
#   1. O sistema NUNCA escreve aqui. Escrever a cada recebimento atropelaria
#      o fechamento dela e quebraria a conciliacao.
#   2. Como e preenchida no fechamento, ela reflete REALIZADO, nao projecao,
#      apesar do titulo da aba dizer "PROJETADO".
#   3. O mes corrente fica incompleto ate o fechamento. Consulta sobre o mes
#      em andamento deve sair dos razoes, nunca daqui.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AbaMatriz:
    aba: str = "2026"
    linha_meses: int = 5
    primeira_coluna_mes: int = 2  # B = janeiro
    ultima_coluna_mes: int = 13  # M = dezembro
    coluna_rotulo: int = 1  # A
    coluna_total_ano: int = 15  # O
    linha_total_entradas: int = 34
    linha_total_saidas: int = 62
    linha_reemb_recebidos: int = 66
    linha_reemb_incorridos: int = 67
    linha_balanco_reembolsos: int = 68
    linha_total_saidas_geral: int = 69
    linha_saldo_liquido: int = 72
    linha_saldo_acumulado: int = 74
    faixa_entradas: tuple[int, int] = (8, 33)
    faixa_saidas: tuple[int, int] = (37, 61)


MATRIZ = AbaMatriz()

# Preenchida a mao no fechamento mensal. Nem a Fase 3 escreve aqui.
MATRIZ_SOMENTE_LEITURA = True


# ---------------------------------------------------------------------------
# Abas historicas - somente leitura, formato irregular
# ---------------------------------------------------------------------------

ABAS_HISTORICAS = {
    "NFs 2025": "Valores gravados como texto (R$ 12.396,22). Pergunta 11.",
    "CONTROLE UNIO": "Controle de contrato encerrado.",
    "CONTROLE RAFAEL": "Despesas de espolio, fora do operacional.",
    "CONTROLE RAFAEL (2)": "Aportes de socio. Valores como texto. Pergunta 11.",
    "CONTROLE PEDRO SALGADO": "Controle avulso, 1 lancamento.",
}


# ---------------------------------------------------------------------------
# DRE BMG - modelo de rentabilidade por equipe
#
# NAO e uma DRE contabil: a receita e calculada por volume de atos x preco
# unitario, nao pelas notas emitidas. Ver pergunta 8 do mapeamento.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AbaDRE:
    aba_geral: str = "GERAL"
    equipes: tuple[str, ...] = ("cartao", "seguro", "CNC")
    linha_faturamento_bruto: int = 31
    linha_imposto: int = 32
    linha_resultado_operacional: int = 37
    linha_receita_preposto: int = 38
    linha_resultado_final: int = 39
    linha_soma_custo: int = 30
    coluna_realizado: int = 5  # E
    coluna_projetado: int = 6  # F


DRE = AbaDRE()

# Precos unitarios usados no modelo (julho/2026).
DRE_PRECO_ATO = {"encerramento": 285.0, "defesa": 238.0, "acordo": 30.0}
DRE_ALIQUOTA_IMPOSTO = 0.20


# ---------------------------------------------------------------------------
# Mapa de migracao de CNPJ (aba NOTAS dos arquivos de faturamento)
#
# Lido do arquivo em tempo de execucao; este e apenas o layout.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AbaNotasCNPJ:
    aba: str = "NOTAS"
    primeira_linha: int = 2
    col_novo_cnpj: int = 1  # A - migra para o CNPJ Rafaela
    col_intermediario: int = 2  # B - em transicao
    col_manter: int = 3  # C - permanece no CNPJ principal


NOTAS_CNPJ = AbaNotasCNPJ()


# ---------------------------------------------------------------------------
# Guarda de seguranca
# ---------------------------------------------------------------------------

# Fase 2 e integralmente somente leitura. Nenhuma funcao de escrita existe no
# codigo. Esta constante e verificada no startup e pelo teste de seguranca.
MODO_SOMENTE_LEITURA = True

# Operacoes de escrita mapeadas na Fase 1, com o risco avaliado. Nenhuma esta
# implementada. Serve de contrato para a Fase 3.
OPERACOES_ESCRITA_PLANEJADAS = {
    "registrar_nota_emitida": "baixo",
    "confirmar_nota_prevista": "baixo",
    "registrar_recebimento": "baixo",
    "registrar_guia_paga": "baixo",
    "registrar_despesa": "baixo",
    "registrar_transferencia": "medio",
    "abrir_nota_debito": "medio",
    "quitar_nota_debito": "medio",
    "fechar_lote_reembolso": "alto",
    # "lancar_matriz_2026" saiu da lista: o financeiro preenche essa aba a mao
    # no fechamento mensal, entao o sistema nao escreve la em fase nenhuma.
}
