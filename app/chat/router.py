# -*- coding: utf-8 -*-
"""Roteador do chat.

Junta as pecas: o modelo escolhe a consulta, o codigo executa e formata.

Duas garantias que este modulo mantem:

1. Nenhum numero vem do modelo. Todo valor exibido foi calculado pelo motor
   de consultas a partir da planilha, e vem acompanhado da origem.
2. Pedido de escrita nao e executado. Na Fase 2 ele e reconhecido, explicado
   e registrado - nunca tentado.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from ..domain import normalize as nz
from ..domain.loader import Repositorio
from ..llm.base import Provedor, montar_contexto
from ..queries import engine as E


@dataclass
class Resposta:
    texto: str
    tipo: str = "consulta"  # consulta | escrita_bloqueada | pergunta | erro
    titulo: Optional[str] = None
    numeros: dict[str, float] = field(default_factory=dict)
    linhas: list[dict[str, Any]] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    fonte: list[str] = field(default_factory=list)
    consulta: Optional[str] = None
    parametros: dict[str, Any] = field(default_factory=dict)
    fornecedor: Optional[str] = None


TEXTO_ESCRITA_BLOQUEADA = (
    "Entendi o pedido, mas ainda não posso alterar planilha.\n\n"
    "Esta versão lê os arquivos e responde, sem nunca escrever neles. O motor "
    "de lançamentos é a próxima fase e ainda depende de uma definição do "
    "financeiro: o que significam as notas de janeiro a junho que ficaram com "
    "a data de recebimento em branco.\n\n"
    "O que anotei do seu pedido: {intencao}\n\n"
    "Enquanto isso, posso consultar qualquer coisa: quanto foi faturado, o que "
    "está em aberto, quanto um cliente deve, ou quais reembolsos faltam."
)


class Roteador:
    def __init__(self, repositorio: Repositorio, provedor: Provedor) -> None:
        self.repositorio = repositorio
        self.provedor = provedor

    # -- entrada principal -------------------------------------------------

    def responder(self, pergunta: str) -> Resposta:
        pergunta = (pergunta or "").strip()
        if not pergunta:
            return Resposta(texto="Pode perguntar.", tipo="pergunta")

        contexto = montar_contexto(E.CATALOGO, dt.date.today())
        try:
            escolha = self.provedor.escolher(pergunta, contexto)
        except Exception as erro:  # falha de rede, credencial, cota
            from ..llm.provedores import ProvedorRegras

            escolha = ProvedorRegras(E.CATALOGO).escolher(pergunta, contexto)
            escolha.fornecedor = f"regras (queda: {type(erro).__name__})"

        if escolha.intencao_de_escrita:
            return Resposta(
                texto=TEXTO_ESCRITA_BLOQUEADA.format(
                    intencao=escolha.intencao_de_escrita
                ),
                tipo="escrita_bloqueada",
                titulo="Lancamento ainda nao disponivel",
                fornecedor=escolha.fornecedor,
            )

        if not escolha.consulta:
            return Resposta(
                texto=escolha.resposta_livre
                or (
                    "Não entendi o que você quer saber. Posso responder sobre "
                    "faturamento, recebimentos, contas a receber, reembolsos, "
                    "guias e movimento das contas."
                ),
                tipo="pergunta",
                fornecedor=escolha.fornecedor,
            )

        try:
            indice = self.repositorio.indice()
            resultado = E.executar(indice, escolha.consulta, escolha.parametros)
        except KeyError:
            return Resposta(
                texto=(
                    f"Não tenho uma consulta chamada '{escolha.consulta}'. "
                    f"Reformule a pergunta."
                ),
                tipo="erro",
                fornecedor=escolha.fornecedor,
            )
        except Exception as erro:
            return Resposta(
                texto=(
                    f"Não consegui ler as planilhas para responder isso. "
                    f"Detalhe técnico: {type(erro).__name__}: {erro}"
                ),
                tipo="erro",
                fornecedor=escolha.fornecedor,
            )

        if resultado.faltou:
            return Resposta(
                texto=resultado.faltou,
                tipo="pergunta",
                consulta=escolha.consulta,
                parametros=escolha.parametros,
                fornecedor=escolha.fornecedor,
            )

        return self._formatar(resultado, escolha, indice)

    # -- formatacao --------------------------------------------------------

    def _formatar(self, resultado: E.Resultado, escolha, indice) -> Resposta:
        avisos = list(resultado.avisos)

        # Avisos de integridade da carga entram quando sao criticos: o usuario
        # precisa saber que a fonte tem problema antes de usar o numero.
        for aviso in indice.avisos:
            if aviso.severidade == "critico":
                avisos.append(f"{aviso.aba}: {aviso.mensagem}")

        return Resposta(
            texto=resultado.resumo,
            tipo="consulta",
            titulo=resultado.titulo,
            numeros=resultado.numeros,
            linhas=[self._linha(l) for l in resultado.linhas],
            avisos=avisos,
            fonte=resultado.fonte,
            consulta=escolha.consulta,
            parametros=escolha.parametros,
            fornecedor=escolha.fornecedor,
        )

    @staticmethod
    def _linha(linha: E.Linha) -> dict[str, Any]:
        dados = asdict(linha)
        dados["valor_formatado"] = nz.moeda(linha.valor)
        return dados

    # -- apoio -------------------------------------------------------------

    def sugestoes(self) -> list[str]:
        return [
            "Quanto faturamos em julho?",
            "Quanto ainda temos para receber?",
            "Quanto o BMG nos deve?",
            "Quais reembolsos estão pendentes?",
            "Quanto saiu do Santander este mês?",
            "Qual a margem da ARG?",
        ]

    def estado(self) -> dict[str, Any]:
        indice = self.repositorio.indice()
        return {
            "carregado_em": indice.carregado_em.strftime("%d/%m/%Y %H:%M")
            if indice.carregado_em
            else None,
            "arquivos": indice.arquivos_lidos,
            "notas": len(indice.notas),
            "lancamentos": len(indice.lancamentos),
            "lotes": len(indice.lotes),
            "manuais": len(indice.manuais),
            "notas_debito": len(indice.notas_debito),
            "avisos": [
                {
                    "severidade": a.severidade,
                    "arquivo": a.arquivo,
                    "aba": a.aba,
                    "mensagem": a.mensagem,
                }
                for a in indice.avisos
            ],
            "fornecedor": self.provedor.nome,
            "somente_leitura": True,
        }
