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
import re
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
        # Lancamento em construcao: o que a usuaria pediu e ainda esta
        # incompleto. Sem isso, a resposta dela a uma pergunta minha chega
        # como frase solta e vira consulta aleatoria.
        self._rascunho: Optional[dict[str, Any]] = None

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

            try:
                escolha = ProvedorRegras(E.CATALOGO).escolher(pergunta, contexto)
                escolha.fornecedor = f"regras (queda: {type(erro).__name__})"
            except Exception as erro2:
                # Nem a queda funcionou. Responder mesmo assim: uma excecao
                # aqui derrubaria a rota e o chat ficaria mudo na tela.
                return Resposta(
                    texto=(
                        "Tive um problema para interpretar essa frase. "
                        "Tente escrever de outro jeito, mais curto.\n\n"
                        f"Detalhe técnico: {type(erro2).__name__}: {erro2}"
                    ),
                    tipo="erro",
                    titulo="Não consegui interpretar",
                )

        # Havia um lancamento pela metade? A frase pode ser a resposta a
        # pergunta que fiz, e nao um pedido novo.
        if self._rascunho and not escolha.operacao:
            complemento = self._complementar(pergunta, escolha)
            if complemento is not None:
                return complemento

        if escolha.operacao:
            if escolha.operacao != "nao_suportada":
                self._rascunho = {
                    "operacao": escolha.operacao,
                    "dados": dict(escolha.dados),
                }
            return self._lancamento(escolha)

        if not escolha.consulta:
            return self._nao_entendi(pergunta, escolha)

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

    # -- quando nao entende ------------------------------------------------

    _SAUDACAO = re.compile(
        r"^\s*(oi|ola|olá|bom dia|boa tarde|boa noite|e ai|eai|opa|"
        r"obrigad[oa]|valeu|tudo bem|beleza|tchau|ate mais|até mais)\b",
        re.I,
    )

    def _nao_entendi(self, pergunta: str, escolha) -> Resposta:
        """Admite que nao entendeu e mostra o que sabe fazer.

        Antes o sistema caia na posicao geral para qualquer frase, entao "oi",
        "obrigado" e "asdf" devolviam o mesmo painel do ano - e parecia que o
        chat tinha travado numa resposta so.
        """
        if escolha.resposta_livre:
            return Resposta(
                texto=escolha.resposta_livre,
                tipo="pergunta",
                fornecedor=escolha.fornecedor,
            )

        if self._SAUDACAO.match(pergunta.strip()):
            return Resposta(
                texto=(
                    "Oi! Pergunte o que quiser sobre o financeiro do "
                    "escritório, em português mesmo. Se quiser ver do que sou "
                    "capaz, peça \"o que você sabe responder\"."
                ),
                tipo="pergunta",
                titulo="Pode perguntar",
                fornecedor=escolha.fornecedor,
            )

        exemplos = [
            "Quanto faturamos em julho?",
            "Quanto ainda temos para receber?",
            "Quanto o BMG nos deve?",
            "Quais reembolsos estão pendentes?",
            "Qual cliente paga mais?",
            "Quanto gastamos com aluguel?",
            "Quanto saiu do Santander este mês?",
        ]
        lista = "\n".join(f"  {e}" for e in exemplos)
        return Resposta(
            texto=(
                f"Não entendi essa. Reformule com o que você quer saber, ou "
                f"experimente uma destas:\n\n{lista}\n\n"
                f"Para lançar, diga o que aconteceu: \"teve uma nota do BMG "
                f"de 100 mil\" ou \"recebemos a nota 240/2026\"."
            ),
            tipo="pergunta",
            titulo="Não entendi",
            fornecedor=escolha.fornecedor,
        )

    # -- continuidade da conversa ------------------------------------------

    # Frases curtas que so fazem sentido como resposta a uma pergunta minha.
    _RESPOSTA_CURTA = re.compile(
        r"^\s*(sim|nao|não|e|é|eh|ok|isso|esse|essa|pode ser|"
        r"principal|matriz|rafaela|individual|simples|"
        r"itau|itaú|inter|inter ?[123]|santander|omie ?cash|"
        r"cliente novo|novo cliente|primeiro|nova)\b",
        re.I,
    )

    def _complementar(self, pergunta: str, escolha) -> Optional[Resposta]:
        """Tenta ler a frase como resposta a um lancamento pela metade.

        So assume isso quando a frase e curta, ou fala de CNPJ, conta, valor
        ou cliente. Pergunta clara de consulta continua sendo consulta.
        """
        from ..llm.provedores import ProvedorRegras

        texto = pergunta.strip()
        curta = len(texto.split()) <= 8
        parece_resposta = bool(self._RESPOSTA_CURTA.match(texto)) or curta
        if not parece_resposta:
            return None

        extrator = ProvedorRegras(E.CATALOGO)
        novos: dict[str, Any] = {}

        baixo = nz.sem_acento(texto).lower()
        if "rafaela" in baixo or "individual" in baixo or "simples" in baixo:
            novos["entidade"] = "rafaela"
        elif "principal" in baixo or "matriz" in baixo:
            novos["entidade"] = "principal"

        conta = extrator._conta(baixo)
        if conta:
            novos["conta"] = conta

        valor = extrator._valor(texto)
        if valor is not None:
            campo = (
                "valor_liquido"
                if self._rascunho["operacao"] == "nota_emitida"
                else "valor"
            )
            novos[campo] = valor

        cliente = extrator._cliente_lancamento(texto)
        if cliente and "cliente" not in self._rascunho["dados"]:
            novos["cliente"] = cliente

        if not novos:
            return None

        self._rascunho["dados"].update(novos)
        escolha.operacao = self._rascunho["operacao"]
        escolha.dados = dict(self._rascunho["dados"])
        return self._lancamento(escolha)

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
        self._rascunho = None  # completou: nao ha mais o que perguntar
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
                        # So o que sera de fato gravado. Celula vazia na
                        # proposta nao e escrita, e mostra-la faria a conta
                        # nao bater com o "gravei N celulas" do final.
                        "celulas": [
                            {"ref": c.ref, "coluna": c.coluna, "valor": c.exibicao}
                            for c in a.celulas
                            if c.valor is not None
                        ],
                    }
                    for a in proposta.alvos
                ],
            },
        )

    def confirmar(self, token: str, usuario: str) -> Resposta:
        """Aplica uma proposta que a usuaria confirmou."""
        from .. import lancamentos as lanc

        self._rascunho = None
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
        self._rascunho = None
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
