# Assistente financeiro - Fase 2 (consultas)

Chatbot que responde perguntas em português sobre as planilhas financeiras do
escritório. **Esta fase é somente leitura: nenhum arquivo é alterado.**

O motor de lançamentos é a Fase 3 e depende de aprovação do mapeamento.

---

## O princípio

A separação pedida no briefing está implementada assim:

| Camada | Responsabilidade | Onde |
|---|---|---|
| Modelo de linguagem | Entender a pergunta e escolher **qual** consulta responde | `app/llm/` |
| Código | Decidir **onde** o dado está e **calcular** o número | `app/queries/engine.py` |
| Mapa declarativo | Guardar arquivo, aba, coluna e vocabulário de cada dado | `app/domain/schema.py` |

O modelo nunca vê endereço de célula, nunca calcula valor e nunca escreve.
Ele devolve apenas `{"consulta": "faturamento", "parametros": {"mes": 7}}`.
Se inventar um nome de consulta que não existe, o código ignora.

Toda resposta traz a origem do número (arquivo, aba e linha), para poder ser
conferida contra a planilha.

---

## Rodar local

```bash
python -m pip install -r requirements.txt
```

```bash
python -m uvicorn app.main:app --reload --port 8077
```

Abra `http://127.0.0.1:8077`.

Sem `APP_USUARIO` e `APP_SENHA` definidos, a aplicação roda aberta em ambiente
local. Em `AMBIENTE=producao` ela recusa subir sem credencial.

A pasta das planilhas é encontrada sozinha no OneDrive. Para apontar outra,
use `PASTA_PLANILHAS`.

---

## Testes

```bash
python -m pytest tests -v
```

Os testes de segurança são o contrato da Fase 2 e falham se alguém introduzir
um caminho de escrita:

- nenhuma chamada capaz de gravar ou apagar arquivo no pacote `app`
- nenhum `open()` em modo de escrita
- todo `load_workbook` com `read_only=True`
- nenhuma rota POST fora das quatro previstas
- nenhuma operação de escrita da Fase 3 implementada
- **os arquivos não mudam no disco depois de rodar todas as consultas**

---

## O que ele responde

| Consulta | Exemplo |
|---|---|
| `faturamento` | Quanto faturamos em julho? |
| `recebimentos` | Quanto recebemos este mês? |
| `a_receber` | Quanto ainda temos para receber? |
| `cliente_posicao` | Quanto o BMG nos deve? |
| `reembolsos_pendentes` | Quais reembolsos estão pendentes? |
| `guias_adiantadas` | Quanto adiantamos em guias este mês? |
| `guias_sem_lote` | Quais guias pagamos e ainda não foram cobradas? |
| `movimento_conta` | Quanto saiu do Santander este mês? Quanto a Omie Cash pagou? |
| `despesas_por_contrato` | Quanto gastamos com o BMG em julho? |
| `margem_cliente` | Qual a margem da ARG? |
| `posicao_geral` | Como estamos? |
| `listar_notas` | Lista as notas de agosto. |

Pedidos de lançamento ("emitimos uma nota de 50 mil") são reconhecidos,
explicados e **não executados**.

---

## Como o sistema lê as planilhas

O mapeamento completo está no relatório da Fase 1. O essencial:

**Faturamento** - cada linha das abas mensais tem um estado, lido de duas
colunas:

| Estado | Coluna A (NF) | Coluna G (recebimento) |
|---|---|---|
| prevista | vazia | vazia |
| pendente | preenchida | `PENDENTE` |
| sem baixa | preenchida | vazia |
| recebida | preenchida | data |

`pendente` e `sem baixa` **nunca são somados juntos em silêncio**. O marcador
`PENDENTE` só passou a ser usado em julho de 2026; antes disso 25 notas
ficaram com a coluna vazia (R$ 357.036,43). Se isso é cobrança viva ou baixa
não registrada é a pergunta 12, em aberto.

**Fluxo de caixa** - a coluna `DESCRIÇÃO` classifica o lançamento;
`TRANSFERÊNCIA ENTRE CONTAS` nunca vira receita nem despesa, e adiantamento
(guia, depósito, acordo) nunca vira custo.

**Aba não é o mesmo que conta.** A aba `SANTANDER` abriga três contas,
separadas pela coluna `BANCO`: Santander, Omie Cash (desde 26/05/2026) e
Inter 3. A Omie Cash não tem aba própria - é ali que ela mora, confirmado
pelo financeiro. Consulta por conta usa `conta_efetiva`, derivada da coluna
`BANCO`, e não a aba.

A coluna `BANCO` só desempata na aba `SANTANDER`. Nas abas `INTER (2)` e
`INTER (3)` ela traz "INTER" genérico, e obedecer a esse texto jogaria os
lançamentos delas para o Inter 1.

**Aba "2026" (matriz mensal)** - preenchida à mão pelo financeiro, uma vez por
mês, na conciliação e no fechamento. Por isso os valores ficam concatenados
dentro da fórmula. **O sistema nunca escreve nela, em fase nenhuma** -
escrever a cada recebimento atropelaria o fechamento. Como é preenchida no
fechamento, reflete realizado, apesar do título dizer "PROJETADO"; e o mês
corrente fica incompleto até fechar, então consulta sobre o mês em andamento
sai dos razões.

**Reembolsos** - três trilhas independentes: lotes de guias do BMG, reembolsos
manuais por processo, e notas de débito de outros clientes.

---

## Armadilhas conhecidas nos arquivos

O carregador detecta e avisa; não corrige nada sozinho.

- **Linhas de subtotal.** Todo razão termina com `=SUBTOTAL(9,...)`, e a aba
  `SANTANDER` tem outro no meio. Lidas como lançamento, dobrariam os totais.
  Descartadas por não terem contraparte, contrato, descrição, data nem banco.
- **Lançamentos espelhados.** 98 linhas do Inter 3 aparecem na aba
  `SANTANDER` (R$ 188.009,96); 97 repetem, com mesma data, valor e
  contraparte, linhas que já estão na aba `INTER (3)`. Tratadas como cópia e
  fora dos totais. Uma sobrou sem par, de R$ 15,44, e o aviso diz isso.
- Abas com espaço no fim do nome (`'julho 2026 '` no arquivo da Rafaela)
- Segundo bloco com layout deslocado nas abas de julho e agosto do CNPJ
  principal, repetido nos dois meses (R$ 83.526,50 - pergunta 7)
- Pendências manuais de 2025 repetidas na aba de 2026 (contadas uma vez só)
- Valores gravados como texto (`"R$ 12.396,22"`) nas abas históricas
- 12 células `#REF!` na aba GERAL da DRE

Os avisos aparecem no botão **Fontes** da interface.

---

## Deploy no Railway

`railway.json` já configura build, comando de início e health check em
`/saude`.

Variáveis obrigatórias em produção:

```
AMBIENTE=producao
APP_USUARIO=
APP_SENHA=
APP_CHAVE_SESSAO=
PASTA_PLANILHAS=
```

**Atenção com as planilhas.** O sistema de arquivos do Railway é efêmero:
arquivo gravado no container se perde a cada deploy. Como esta fase só lê, o
risco hoje é o serviço subir sem encontrar os arquivos. Antes da Fase 3 isso
precisa ser resolvido, e as opções são:

1. volume persistente montado no serviço, com `PASTA_PLANILHAS` apontando para ele
2. armazenamento externo (S3 ou equivalente), baixando na inicialização
3. manter o OneDrive como fonte, com sincronização

A decisão fica para quando a escrita entrar, porque aí a durabilidade do
arquivo passa a ser crítica.

---

## Segredos

Nada de credencial no repositório. `.env` está no `.gitignore` junto com
`*.xlsx` - dado financeiro real do escritório não vai para o git.

`ANTHROPIC_API_KEY` é opcional: sem ela, o sistema usa o interpretador local
por regras e continua respondendo. Omie e XJus não são acessados nesta fase.

---

## Estrutura

```
app/
  domain/
    schema.py       mapa declarativo: onde cada dado mora
    models.py       objetos de domínio e estados
    normalize.py    datas, valores e nomes de cliente
    loader.py       leitura (read_only) e cache por mtime
  queries/
    engine.py       consultas determinísticas e catálogo
  llm/
    base.py         contrato do provedor e instrução
    provedores.py   Anthropic e interpretador por regras
  chat/
    router.py       intenção -> consulta -> resposta
  web/              páginas e estáticos
  main.py           rotas e sessão
  config.py         variáveis de ambiente
tests/
  test_seguranca.py contrato de somente leitura
```

## Próxima fase

Respondido pelo financeiro em agosto de 2026, e já refletido no código:

- a aba `2026` é preenchida à mão no fechamento mensal, então o sistema não
  escreve nela em fase nenhuma (isso encerrou as perguntas 1 e 2)
- os pagamentos da Omie Cash ficam na aba `SANTANDER`, identificados pela
  coluna `BANCO` (pergunta 4)

Falta uma resposta para liberar a escrita: **o que significam as notas de
janeiro a junho que ficaram com a data de recebimento em branco** (pergunta
12, R$ 357.036,43). Enquanto não vier, o sistema informa os dois números
separados e nunca os soma.

Depois disso, a ordem combinada é: as seis operações de risco baixo primeiro
(registrar nota emitida, confirmar nota prevista, registrar recebimento,
registrar guia paga, registrar despesa, abrir e quitar ND), e fechar lote de
reembolso só com decisão explícita, porque exige estender o `SUM` do mês.
