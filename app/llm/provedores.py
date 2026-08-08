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
        if not e_pergunta and any(v in texto.lower() for v in _VERBOS_ESCRITA):
            return Escolha(
                consulta=None,
                intencao_de_escrita=texto,
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
        return Escolha(
            consulta=nome,
            parametros=dados.get("parametros") or {},
            intencao_de_escrita=dados.get("intencao_de_escrita"),
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
