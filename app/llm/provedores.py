# -*- coding: utf-8 -*-
"""Implementacoes de provedor.

- Anthropic: usa a API quando ANTHROPIC_API_KEY esta definida.
- Regras: interpretador local por padrao textual, sem rede e sem credencial.

O interpretador por regras nao e enfeite: ele mantem a aplicacao respondendo
quando a chave nao esta configurada ou a API falha, e serve de referencia nos
testes, onde chamada de rede deixaria o resultado instavel.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any, Optional

from ..domain import normalize as nz
from .base import INSTRUCAO, Escolha, Provedor, montar_contexto


# ---------------------------------------------------------------------------
# Interpretador por regras
# ---------------------------------------------------------------------------

_VERBOS_ESCRITA = (
    "registre",
    "registra",
    "registrar",
    "lanca",
    "lança",
    "lancar",
    "lançar",
    "emitimos",
    "emitir",
    "emite",
    "pagamos",
    "pagar",
    "recebemos hoje",
    "reembolsou",
    "da baixa",
    "dar baixa",
    "baixa n",
    "altera",
    "alterar",
    "corrige",
    "corrigir",
    "atualiza",
    "atualizar",
    "adiciona",
    "adicionar",
    "cadastra",
    "cadastrar",
    "grava",
    "gravar",
)

# Marcas de pergunta. Uma frase interrogativa nunca e ordem de lancamento,
# mesmo contendo verbo de acao no passado ("Quais guias pagamos?").
_MARCAS_DE_PERGUNTA = (
    "quanto",
    "quantos",
    "quantas",
    "qual",
    "quais",
    "quando",
    "onde",
    "quem",
    "como",
    "o que",
    "por que",
    "me mostra",
    "me mostre",
    "mostra",
    "mostre",
    "lista",
    "listar",
    "me da",
    "me de",
    "resumo",
)

_MESES_TEXTO = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
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


class ProvedorRegras(Provedor):
    """Interpretador local. Sem rede, sem credencial."""

    nome = "regras"

    def __init__(self, catalogo: dict) -> None:
        self.catalogo = catalogo

    def disponivel(self) -> bool:
        return True

    def escolher(self, pergunta: str, contexto: str) -> Escolha:
        texto = pergunta.strip()
        baixo = nz.sem_acento(texto.lower())
        hoje = dt.date.today()

        # Pergunta vence verbo de acao: "Quais guias pagamos?" e consulta,
        # "Pagamos a guia da Maria" e pedido de lancamento.
        e_pergunta = texto.rstrip().endswith("?") or any(
            baixo.lstrip().startswith(m) for m in _MARCAS_DE_PERGUNTA
        )
        if not e_pergunta:
            lancamento = self._lancamento(texto, baixo)
            if lancamento:
                return Escolha(
                    consulta=None,
                    operacao=lancamento[0],
                    dados=lancamento[1],
                    fornecedor=self.nome,
                )

        parametros: dict[str, Any] = {}

        for nome_mes, numero in _MESES_TEXTO.items():
            if nz.sem_acento(nome_mes) in baixo:
                parametros["mes"] = numero
                break
        if "mes" not in parametros and (
            "este mes" in baixo or "esse mes" in baixo or "mes atual" in baixo
        ):
            parametros["mes"] = hoje.month
        if "mes passado" in baixo:
            parametros["mes"] = hoje.month - 1 or 12

        ano = re.search(r"\b(20\d{2})\b", baixo)
        parametros["ano"] = int(ano.group(1)) if ano else 2026

        if "rafaela" in baixo or "individual" in baixo or "simples" in baixo:
            parametros["entidade"] = "rafaela"
        elif "principal" in baixo or "matriz" in baixo:
            parametros["entidade"] = "principal"

        cliente = self._cliente(texto)
        if cliente:
            parametros["cliente"] = cliente

        conta = self._conta(baixo)
        if conta:
            parametros["conta"] = conta

        nome = self._consulta(baixo, parametros)
        return Escolha(consulta=nome, parametros=parametros, fornecedor=self.nome)

    # -- lancamentos -------------------------------------------------------

    # Verbos que indicam que o dinheiro ENTROU, nao que a nota foi emitida.
    _RECEBER = (
        "recebemos", "recebeu", "pagou", "quitou",
        "deu baixa", "dar baixa", "foi paga", "foi pago",
    )
    # Estes so valem perto de dinheiro: "entrou um cliente novo" nao e baixa.
    _RECEBER_SE_DINHEIRO = ("caiu", "entrou")
    _DINHEIRO = re.compile(
        r"(r\$|reais|dinheiro|pagamento|valor|deposito|depósito|"
        r"\d[\d\.,]*\s*(mil|milh)|na conta|no itau|no itaú|no santander)",
        re.I,
    )
    _EMITIR = (
        "emitimos", "emiti", "emitiu", "emitida", "emitido", "faturamos",
        "faturei", "faturado para", "teve uma nota", "saiu uma nota",
        "nota nova", "nova nota", "registra uma nota", "registrar uma nota",
        "lancar uma nota", "lançar uma nota", "primeira nota",
    )

    @staticmethod
    def _negado(baixo: str, termo: str) -> bool:
        """True quando o termo aparece negado: "ainda nao recebemos".

        Sem isto, "a nota foi emitida mas ainda nao recebemos o pagamento"
        vira baixa de recebimento - o oposto do que a pessoa disse.
        """
        for m in re.finditer(re.escape(termo), baixo):
            antes = baixo[max(0, m.start() - 26):m.start()]
            if not re.search(r"\b(nao|nunca|sem|ainda nao|nem)\b", antes):
                return False  # ao menos uma ocorrencia afirmativa
        return True

    def _ocorre(self, baixo: str, termos) -> bool:
        """Termo presente e nao negado."""
        return any(t in baixo and not self._negado(baixo, t) for t in termos)

    def _lancamento(self, texto: str, baixo: str):
        """Extrai (operacao, dados) da frase. Devolve None se nao for lancamento."""
        tem = lambda ts: any(t in baixo for t in ts)
        emitiu = self._ocorre(baixo, self._EMITIR)
        recebeu = self._ocorre(baixo, self._RECEBER)
        if not recebeu and self._DINHEIRO.search(texto):
            recebeu = self._ocorre(baixo, self._RECEBER_SE_DINHEIRO)

        tem_valor = self._valor(texto) is not None

        # Emissao ganha de recebimento negado: quem diz "emitimos a nota mas
        # ainda nao recebemos" esta registrando a NOTA, nao a baixa.
        if emitiu:
            operacao = "nota_emitida"
        elif recebeu:
            operacao = "recebimento"
        elif "nota" in baixo and (tem(_VERBOS_ESCRITA) or tem_valor):
            # "nota para a T Mining de 10 mil" - fala de nota e de valor, sem
            # verbo. Nao existe consulta que se pareca com isso.
            operacao = "nota_emitida"
        elif tem(_VERBOS_ESCRITA):
            # Pedido de escrita que ainda nao sei fazer: devolve sem operacao
            # para o roteador explicar, em vez de fingir que entendeu.
            return ("nao_suportada", {"frase": texto})
        else:
            return None

        dados: dict[str, Any] = {}

        nf = re.search(r"\b(\d{1,4}\s*/\s*\d{2,4})\b", texto)
        if nf:
            dados["numero"] = nf.group(1).replace(" ", "")

        valor = self._valor(texto)
        if valor is not None:
            dados["valor_bruto" if operacao == "nota_emitida" else "valor"] = valor

        cliente = self._cliente_lancamento(texto)
        if cliente:
            dados["cliente"] = cliente

        if "rafaela" in baixo or "individual" in baixo:
            dados["entidade"] = "rafaela"
        elif "principal" in baixo or "matriz" in baixo:
            dados["entidade"] = "principal"

        conta = self._conta(baixo)
        if conta and operacao == "recebimento":
            dados["conta"] = conta

        return (operacao, dados)

    @staticmethod
    def _valor(texto: str):
        """Le "50 mil", "R$ 1.234,56", "100000" ou "1,5 milhao"."""
        t = texto.replace(" ", " ")
        # "milhao" antes de "mil": na alternancia, "mil" casaria o prefixo de
        # "milhao" e 1,5 milhao viraria 1.500.
        m = re.search(
            r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?|\d+(?:\.\d{1,2})?)"
            r"\s*(milh(?:ao|ão|oes|ões)|mil)?",
            t, re.I,
        )
        if not m:
            return None
        bruto, escala = m.group(1), (m.group(2) or "").lower()
        # Numero de nota nao e valor: "240/2026" nao vira 240.
        if re.search(re.escape(bruto) + r"\s*/", t):
            return None
        if "." in bruto and "," in bruto:
            bruto = bruto.replace(".", "").replace(",", ".")
        elif "," in bruto:
            bruto = bruto.replace(",", ".")
        elif bruto.count(".") > 1 or re.match(r"^\d{1,3}(\.\d{3})+$", bruto):
            bruto = bruto.replace(".", "")
        try:
            n = float(bruto)
        except ValueError:
            return None
        # "milh" antes de "mil": startswith("mil") tambem pega "milhao".
        if escala.startswith("milh"):
            n *= 1_000_000
        elif escala.startswith("mil"):
            n *= 1000
        return round(n, 2)

    # Sufixos societarios que fazem parte do nome e devem ser mantidos.
    _SUFIXO_EMPRESA = r"(?:ltda|s\.?/?a\.?|me|epp|eireli|sociedade|holding)"

    @staticmethod
    def _cliente_lancamento(texto: str):
        """Nome do cliente numa frase de lancamento.

        Precisa pegar o nome INTEIRO: "a ABC Participacoes Ltda" e o nome que
        vai para a planilha, nao "ABC". Por isso aceita palavra capitalizada
        depois da primeira, e nao so caixa alta.
        """
        ignorar = {
            "NOTA", "NF", "CNPJ", "PENDENTE", "ND", "R$", "MIL", "MILHAO",
            "MILHÃO", "REAIS", "VALOR", "CLIENTE", "CONTA", "BANCO", "HOJE",
            "ONTEM", "RAFAELA", "PRINCIPAL", "MATRIZ", "FECHAMOS", "ENTROU",
            "CONTRATO", "HONORARIOS", "HONORÁRIOS", "PAGAMENTO", "PRIMEIRA",
        }
        # Uma palavra do nome: comeca com maiuscula, ou e sigla em caixa alta.
        palavra = r"[A-ZÀ-Ú][\wÀ-ú&\.\-]*"
        padroes = (
            # "cliente novo, a ABC Participacoes Ltda"
            rf"(?:cliente|empresa)\s+(?:nov[oa]\s*,?\s*)?(?:a|o)?\s*"
            rf"({palavra}(?:\s+{palavra}){{0,4}})",
            # "para a ABC Participacoes Ltda"
            rf"(?:para|pro|pra)\s+(?:a\s+|o\s+)?({palavra}(?:\s+{palavra}){{0,4}})",
            # "nota do BMG", "da FLAPA"
            rf"\b(?:do|da|de)\s+({palavra}(?:\s+{palavra}){{0,3}})",
            # sigla solta em caixa alta
            r"\b([A-ZÀ-Ú]{2,}(?:\s+[A-ZÀ-Ú0-9&\.]{2,}){0,3})\b",
        )
        for padrao in padroes:
            for m in re.finditer(padrao, texto):
                cand = m.group(1).strip(" ,-")
                # Corta em conectivo, mas preserva sufixo societario.
                cand = re.split(
                    r"\s+(?:de|no|na|em|por|com|que|referente)\s+", cand
                )[0].strip(" ,-")
                # O nome termina no sufixo societario, quando houver: em
                # "ABC Participacoes Ltda. Fechamos um contrato", o nome
                # acaba no "Ltda".
                # Guloso de proposito: "FCF Holding Ltda" termina no Ltda,
                # nao no Holding.
                sufixo = re.search(
                    rf"^(.*\b{ProvedorRegras._SUFIXO_EMPRESA}\.?)(?:\s|$)",
                    cand, re.I,
                )
                if sufixo:
                    cand = sufixo.group(1)
                else:
                    # Sem sufixo, corta no fim da frase.
                    cand = re.split(r"\.\s+[A-ZÀ-Ú]", cand)[0]
                cand = cand.strip(" ,-")
                if not cand or cand.upper() in ignorar:
                    continue
                if re.fullmatch(r"[\d\.,/]+", cand):
                    continue
                if nz.numero_mes(cand) is not None:
                    continue
                # Uma palavra so, minuscula, quase sempre e falso positivo.
                if cand.islower():
                    continue
                return cand
        return None

    # -- heuristicas -------------------------------------------------------

    def _consulta(self, baixo: str, parametros: dict) -> str:
        tem = lambda *ts: any(t in baixo for t in ts)

        if tem("reembolso", "reembolsar", "reembolsos"):
            if tem("guia", "adiantamos", "adiantado", "adiantou"):
                if tem("sem lote", "nao cobrad", "nao foram cobrad", "nao reembolsad"):
                    return "guias_sem_lote"
                return "guias_adiantadas"
            return "reembolsos_pendentes"

        if tem("guia"):
            if tem("nao reembolsad", "nao foram reembolsad", "sem lote", "pendente"):
                return "guias_sem_lote"
            return "guias_adiantadas"

        if tem("deve", "devendo", "divida", "posicao do", "posicao da"):
            return "cliente_posicao"

        if tem("a receber", "para receber", "em aberto", "pendente", "falta receber"):
            return "a_receber"

        if tem("margem", "dre", "rentabilidade", "lucro"):
            return "margem_cliente"

        if tem("saiu", "gastamos", "gasto", "despesa", "saida", "pagamos"):
            if parametros.get("conta"):
                return "movimento_conta"
            if parametros.get("cliente"):
                return "despesas_por_contrato"
            return "movimento_conta"

        if tem("entrou", "recebemos", "recebido", "recebimento", "caiu"):
            return "recebimentos"

        if tem("faturamos", "faturado", "faturamento", "emitimos", "notas emitidas"):
            return "faturamento"

        if tem("lista", "listar", "quais notas", "me mostra as notas"):
            return "listar_notas"

        if tem("resumo", "panorama", "como estamos", "posicao geral", "geral"):
            return "posicao_geral"

        if parametros.get("conta"):
            return "movimento_conta"
        if parametros.get("cliente"):
            return "cliente_posicao"
        return "posicao_geral"

    def _cliente(self, texto: str) -> Optional[str]:
        padroes = (
            r"(?:cliente|do|da|de|com|para o|para a)\s+([A-ZÀ-Ú][A-ZÀ-Ú0-9&\.\s]{2,30})",
            r"\b([A-ZÀ-Ú]{2,}(?:\s+[A-ZÀ-Ú0-9&\.]{2,}){0,3})\b",
        )
        ignorar = {
            "DRE",
            "NF",
            "CNPJ",
            "PENDENTE",
            "OK",
            "ND",
            "R$",
            "IA",
            "QUANTO",
            "QUAIS",
            "QUAL",
        }
        for padrao in padroes:
            for achado in re.finditer(padrao, texto):
                candidato = achado.group(1).strip(" .")
                if candidato.upper() in ignorar or len(candidato) < 2:
                    continue
                if nz.numero_mes(candidato) is not None:
                    continue
                return candidato
        return None

    def _conta(self, baixo: str) -> Optional[str]:
        # Omie Cash antes de Santander: os lancamentos dela moram na aba do
        # Santander, e quem pergunta pela Omie quer so a Omie.
        if "omie" in baixo or "acash" in baixo:
            return "omie_cash"
        if "santander" in baixo:
            return "santander"
        if "inter 3" in baixo or "inter3" in baixo:
            return "inter3"
        if "inter 2" in baixo or "inter2" in baixo:
            return "inter2"
        if "inter" in baixo:
            return "inter"
        if "itau" in baixo:
            return "itau"
        return None


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class ProvedorAnthropic(Provedor):
    """Usa a API da Anthropic. Credencial exclusivamente por variavel de ambiente."""

    nome = "anthropic"

    def __init__(self, catalogo: dict, modelo: Optional[str] = None) -> None:
        self.catalogo = catalogo
        self.modelo = modelo or os.environ.get("LLM_MODELO", "claude-sonnet-4-5")
        self._cliente = None

    def disponivel(self) -> bool:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def _obter_cliente(self):
        if self._cliente is None:
            import anthropic

            self._cliente = anthropic.Anthropic(
                api_key=os.environ["ANTHROPIC_API_KEY"]
            )
        return self._cliente

    def escolher(self, pergunta: str, contexto: str) -> Escolha:
        cliente = self._obter_cliente()
        resposta = cliente.messages.create(
            model=self.modelo,
            max_tokens=400,
            system=INSTRUCAO + "\n\n" + contexto,
            messages=[{"role": "user", "content": pergunta}],
        )
        bruto = "".join(
            bloco.text for bloco in resposta.content if bloco.type == "text"
        ).strip()
        return self._interpretar(bruto)

    def _interpretar(self, bruto: str) -> Escolha:
        texto = bruto.strip()
        if texto.startswith("```"):
            texto = re.sub(r"^```[a-z]*\n?", "", texto)
            texto = re.sub(r"\n?```$", "", texto).strip()
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            achado = re.search(r"\{.*\}", texto, re.S)
            if not achado:
                return Escolha(
                    consulta=None,
                    resposta_livre="Nao consegui interpretar a pergunta.",
                    fornecedor=self.nome,
                )
            dados = json.loads(achado.group(0))

        nome = dados.get("consulta")
        if nome is not None and nome not in self.catalogo:
            # O modelo inventou um nome. O codigo nao obedece.
            nome = None

        operacao = dados.get("operacao")
        if operacao is not None:
            from .. import lancamentos as lanc

            if operacao not in lanc.OPERACOES:
                operacao = "nao_suportada"

        return Escolha(
            consulta=nome,
            parametros=dados.get("parametros") or {},
            operacao=operacao,
            dados=dados.get("dados") or {},
            resposta_livre=dados.get("resposta_livre"),
            fornecedor=self.nome,
        )


# ---------------------------------------------------------------------------
# Selecao
# ---------------------------------------------------------------------------


def obter_provedor(catalogo: dict) -> Provedor:
    """Escolhe o provedor conforme o ambiente, com queda para regras."""
    escolhido = os.environ.get("LLM_PROVEDOR", "auto").strip().lower()

    if escolhido in ("regras", "local", "none"):
        return ProvedorRegras(catalogo)

    if escolhido in ("auto", "anthropic"):
        provedor = ProvedorAnthropic(catalogo)
        if provedor.disponivel():
            return provedor
        if escolhido == "anthropic":
            raise RuntimeError(
                "LLM_PROVEDOR=anthropic, mas ANTHROPIC_API_KEY nao esta definida "
                "ou o pacote anthropic nao esta instalado."
            )

    return ProvedorRegras(catalogo)
