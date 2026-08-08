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
    # consulta | confirmacao | aplicado | pergunta | erro
    texto: str
    tipo: str = "consulta"
    titulo: Optional[str] = None
    numeros: dict[str, float] = field(default_factory=dict)
    linhas: list[dict[str, Any]] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    fonte: list[str] = field(default_factory=list)
    consulta: Optional[str] = None
    parametros: dict[str, Any] = field(default_factory=dict)
    fornecedor: Optional[str] = None
    # Proposta de lancamento aguardando confirmacao.
    proposta: Optional[dict[str, Any]] = None


TEXTO_NAO_SUPORTADA = (
    "Entendi que é um lançamento, mas ainda só sei fazer dois: registrar uma "
    "nota emitida e dar baixa num recebimento.\n\n"
    "Guias judiciais, notas de débito, despesas e transferências entram "
    "depois. Por enquanto esses continuam sendo lançados direto na planilha."
)


class Roteador:
    def __init__(self, repositorio: Repositorio, provedor: Provedor) -> None:
        self.repositorio = repositorio
        self.provedor = provedor
        # Propostas montadas e ainda nao confirmadas, por token. Ficam so em
        # memoria: se o servico reiniciar, a usuaria refaz o pedido - melhor
        # do que aplicar algo que ela nao viu.
        self._pendentes: dict[str, Any] = {}

    # -- entrada principal -------------------------------------------------

    def responder(self, pergunta: str) -> Resposta:
        pergunta = (pergunta or "").strip()
        if not pergunta:
            return Resposta(texto="Pode perguntar.", tipo="pergunta")

        faltando = self._planilhas_faltando()
        if faltando:
            nomes = "\n".join(f"  - {n}" for n in faltando)
            return Resposta(
                texto=(
                    f"Ainda não tenho as planilhas para consultar. "
                    f"{len(faltando)} arquivo(s) faltando:\n\n{nomes}\n\n"
                    f"Envie pela tela Planilhas, no topo da página."
                ),
                tipo="erro",
                titulo="Faltam planilhas",
            )

        contexto = montar_contexto(E.CATALOGO, dt.date.today())
        try:
            escolha = self.provedor.escolher(pergunta, contexto)
        except Exception as erro:  # falha de rede, credencial, cota
            from ..llm.provedores import ProvedorRegras

            escolha = ProvedorRegras(E.CATALOGO).escolher(pergunta, contexto)
            escolha.fornecedor = f"regras (queda: {type(erro).__name__})"

        if escolha.operacao:
            return self._lancamento(escolha)

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

    # -- lancamentos -------------------------------------------------------

    def _lancamento(self, escolha) -> Resposta:
        """Monta a proposta e devolve para confirmacao. NAO escreve."""
        from .. import lancamentos as lanc

        if escolha.operacao == "nao_suportada":
            return Resposta(
                texto=TEXTO_NAO_SUPORTADA,
                tipo="erro",
                titulo="Ainda não sei fazer esse lançamento",
                fornecedor=escolha.fornecedor,
            )

        try:
            indice = self.repositorio.indice()
            proposta = lanc.propor(indice, escolha.operacao, escolha.dados)
        except lanc.LancamentoRecusado as erro:
            return Resposta(texto=str(erro), tipo="erro", titulo="Não posso fazer isso")
        except Exception as erro:
            return Resposta(
                texto=(
                    f"Não consegui montar o lançamento. "
                    f"Detalhe técnico: {type(erro).__name__}: {erro}"
                ),
                tipo="erro",
            )

        if not proposta.pronta:
            faltando = "\n".join(f"- {f}" for f in proposta.faltando)
            inferido = "".join(
                f"\n\nJá tenho: {k.lower()} = {v}" for k, v in proposta.inferido.items()
            )
            return Resposta(
                texto=f"Antes de gravar, preciso saber:\n\n{faltando}{inferido}",
                tipo="pergunta",
                titulo="Falta um dado",
                fornecedor=escolha.fornecedor,
            )

        self._pendentes[proposta.token] = proposta
        return Resposta(
            texto=proposta.resumo,
            tipo="confirmacao",
            titulo="Confirma este lançamento?",
            avisos=proposta.avisos,
            fornecedor=escolha.fornecedor,
            proposta={
                "token": proposta.token,
                "tipo": proposta.tipo,
                "inferido": proposta.inferido,
                "alvos": [
                    {
                        "arquivo": a.arquivo,
                        "aba": a.aba.strip(),
                        "linha": a.linha,
                        "acao": a.acao,
                        "celulas": [
                            {"ref": c.ref, "coluna": c.coluna, "valor": c.exibicao}
                            for c in a.celulas
                        ],
                    }
                    for a in proposta.alvos
                ],
            },
        )

    def confirmar(self, token: str, usuario: str) -> Resposta:
        """Aplica uma proposta que a usuaria confirmou."""
        from .. import lancamentos as lanc

        proposta = self._pendentes.pop(token, None)
        if proposta is None:
            return Resposta(
                texto=(
                    "Essa proposta não está mais em aberto. Ela pode ter sido "
                    "aplicada, cancelada, ou o serviço reiniciou. Refaça o "
                    "pedido que eu monto de novo."
                ),
                tipo="erro",
                titulo="Proposta expirada",
            )

        try:
            feito = lanc.aplicar(self.repositorio.base, proposta, usuario)
        except lanc.LancamentoRecusado as erro:
            return Resposta(texto=str(erro), tipo="erro", titulo="Não gravei nada")
        except Exception as erro:
            return Resposta(
                texto=(
                    f"Falhou ao gravar. A cópia anterior está em _backups. "
                    f"Detalhe técnico: {type(erro).__name__}: {erro}"
                ),
                tipo="erro",
                titulo="Não deu certo",
            )

        self.repositorio.recarregar()
        quantas = len(feito["celulas"])
        onde = ", ".join(sorted({c.split("!")[0] for c in feito["celulas"]}))
        copias = (
            " Guardei cópia dos arquivos antes de mexer."
            if feito["backups"] else ""
        )
        return Resposta(
            texto=(
                f"Pronto. Gravei {quantas} células em {onde}.{copias} "
                f"As consultas já enxergam o lançamento."
            ),
            tipo="aplicado",
            titulo="Lançamento registrado",
        )

    def cancelar(self, token: str) -> Resposta:
        existia = self._pendentes.pop(token, None) is not None
        return Resposta(
            texto=(
                "Cancelado. Nada foi gravado."
                if existia
                else "Essa proposta já não estava em aberto. Nada foi gravado."
            ),
            tipo="aplicado",
            titulo="Cancelado",
        )

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

    def _planilhas_faltando(self) -> list[str]:
        """Quais dos arquivos esperados ainda nao chegaram na pasta."""
        from .. import arquivos as arq

        return arq.faltando(self.repositorio.base)

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
