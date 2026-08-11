/* Interface do chat. Somente leitura: nao existe rota de escrita para chamar. */
(function () {
  "use strict";

  var conversa = document.getElementById("conversa");
  var boasVindas = document.getElementById("boas-vindas");
  var form = document.getElementById("form");
  var entrada = document.getElementById("entrada");
  var enviar = document.getElementById("enviar");
  var painel = document.getElementById("painel");
  var painelCorpo = document.getElementById("painel-corpo");

  var ROTULOS = {
    faturado: "Faturado",
    recebido: "Recebido",
    pendente: "Em aberto (PENDENTE)",
    sem_baixa: "Em aberto (sem marcador)",
    previsto: "Previsto",
    total: "Total",
    lotes: "Lotes de guias",
    manuais: "Reembolsos manuais",
    notas_debito: "Notas de débito",
    entradas: "Entradas",
    saidas: "Saídas",
    resultado: "Resultado",
    transferencias_recebidas: "Transf. recebidas",
    transferencias_enviadas: "Transf. enviadas",
    em_aberto: "Em aberto",
    devido: "Total devido",
    recebido_2026: "Recebido em 2026",
    adiantado: "Adiantado",
    custo: "Custo",
    custo_direto: "Custo direto",
    receita: "Receita",
    margem: "Margem",
    margem_pct: "Margem %",
    reembolsos_abertos: "Reembolsos em aberto",
    lancamentos: "Lançamentos",
    notas: "Notas",
    quantidade: "Quantidade"
  };

  var SEM_MOEDA = { margem_pct: true, lancamentos: true, notas: true, quantidade: true };

  function esc(t) {
    return String(t == null ? "" : t)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function moeda(v) {
    if (v == null) return "-";
    return "R$ " + Number(v).toLocaleString("pt-BR", {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }

  function elemento(html) {
    var d = document.createElement("div");
    d.innerHTML = html.trim();
    return d.firstElementChild;
  }

  function rolar() {
    conversa.scrollTop = conversa.scrollHeight;
  }

  function esconderBoasVindas() {
    if (boasVindas && boasVindas.parentNode) {
      boasVindas.parentNode.removeChild(boasVindas);
      boasVindas = null;
    }
  }

  function addUsuario(texto) {
    esconderBoasVindas();
    var turno = elemento('<div class="turno"></div>');
    var msg = elemento('<div class="msg-usuario"></div>');
    msg.textContent = texto;
    turno.appendChild(msg);
    conversa.appendChild(turno);
    rolar();
  }

  /* Remover so se ainda estiver na tela. Chamar removeChild duas vezes lanca
     TypeError, e se isso acontecer dentro do catch a resposta some sem
     explicacao nenhuma. */
  function removerPensando(turno) {
    if (turno && turno.parentNode) turno.parentNode.removeChild(turno);
  }

  function addPensando() {
    var turno = elemento(
      '<div class="turno" data-pensando="1">' +
      '<div class="resposta"><div class="pensando">' +
      "<span></span><span></span><span></span></div></div></div>"
    );
    conversa.appendChild(turno);
    rolar();
    return turno;
  }

  function blocoNumeros(numeros) {
    var chaves = Object.keys(numeros || {});
    if (!chaves.length) return "";
    var html = '<div class="numeros">';
    chaves.forEach(function (k) {
      var v = numeros[k];
      var texto = SEM_MOEDA[k]
        ? (k === "margem_pct" ? Number(v).toFixed(1) + "%" : String(Math.round(v)))
        : moeda(v);
      html += '<div class="numero"><span class="rot">' + esc(ROTULOS[k] || k) +
        '</span><span class="val">' + esc(texto) + "</span></div>";
    });
    return html + "</div>";
  }

  function blocoLinhas(linhas) {
    if (!linhas || !linhas.length) return "";
    var html = '<details class="linhas"><summary>Ver as ' + linhas.length +
      " linhas que produziram esse número</summary>" +
      '<div class="tabela-wrap"><table class="linhas-tab"><tbody>';
    linhas.forEach(function (l) {
      html += "<tr><td>";
      html += '<span class="rotulo">' + esc(l.rotulo) + "</span>";
      if (l.detalhe) html += '<span class="detalhe">' + esc(l.detalhe) + "</span>";
      if (l.estado) html += '<span class="marca-estado">' + esc(l.estado) + "</span>";
      if (l.origem) html += '<span class="origem">' + esc(l.origem) + "</span>";
      html += '</td><td class="valor">' + esc(l.valor_formatado || "") + "</td></tr>";
    });
    return html + "</tbody></table></div></details>";
  }

  function blocoAvisos(avisos) {
    if (!avisos || !avisos.length) return "";
    return avisos.map(function (a) {
      var critico = /pergunta \d+|duplic|identicas|idênticas/i.test(a);
      return '<div class="aviso' + (critico ? " critico" : "") + '">' +
        '<span class="icone">!</span><span>' + esc(a) + "</span></div>";
    }).join("");
  }

  function blocoProposta(p) {
    if (!p) return "";
    var html = '<div class="proposta">';

    var chaves = Object.keys(p.inferido || {});
    if (chaves.length) {
      html += '<div class="inferido"><span class="inferido-tit">Preenchi a partir do histórico</span>';
      chaves.forEach(function (k) {
        html += "<div><b>" + esc(k) + ":</b> " + esc(p.inferido[k]) + "</div>";
      });
      html += "</div>";
    }

    (p.alvos || []).forEach(function (a) {
      html += '<div class="alvo">';
      html += '<div class="alvo-cab"><span class="alvo-acao">' + esc(a.acao) + "</span>" +
        '<span class="alvo-onde">' + esc(a.aba) + " · linha " + esc(a.linha) + "</span></div>";
      html += '<div class="alvo-arquivo">' + esc(a.arquivo) + "</div>";
      html += '<table class="alvo-tab"><tbody>';
      (a.celulas || []).forEach(function (c) {
        html += "<tr><td class=\"cel-ref\">" + esc(c.ref) + "</td>" +
          "<td class=\"cel-col\">" + esc(c.coluna) + "</td>" +
          "<td class=\"cel-val\">" + esc(c.valor) + "</td></tr>";
      });
      html += "</tbody></table></div>";
    });

    html += '<div class="proposta-acoes">' +
      '<button type="button" class="btn-confirmar" data-token="' + esc(p.token) + '">Confirmar e gravar</button>' +
      '<button type="button" class="btn-cancelar" data-token="' + esc(p.token) + '">Cancelar</button>' +
      "</div>";
    return html + "</div>";
  }

  function addResposta(dados) {
    var classe = "resposta";
    var titulo = dados.titulo || "";
    if (dados.tipo === "confirmacao") classe += " confirmacao";
    if (dados.tipo === "aplicado") classe += " aplicado";
    if (dados.tipo === "erro") { classe += " erro"; titulo = titulo || "Não deu certo"; }

    var html = '<div class="turno"><div class="' + classe + '">';
    if (titulo) html += "<h3>" + esc(titulo) + "</h3>";
    html += '<p class="texto">' + esc(dados.texto) + "</p>";
    html += blocoNumeros(dados.numeros);
    html += blocoLinhas(dados.linhas);
    html += blocoProposta(dados.proposta);
    html += blocoAvisos(dados.avisos);
    if (dados.fonte && dados.fonte.length) {
      html += '<div class="fonte">Fonte: ' + esc(dados.fonte.join(" · ")) + "</div>";
    }
    html += "</div></div>";
    conversa.appendChild(elemento(html));
    rolar();
  }

  /* Confirmar e cancelar ficam em delegacao: o cartao nasce depois da carga. */
  conversa.addEventListener("click", function (e) {
    var confirmar = e.target.closest(".btn-confirmar");
    var cancelar = e.target.closest(".btn-cancelar");
    if (!confirmar && !cancelar) return;

    var botao = confirmar || cancelar;
    var caixa = botao.closest(".proposta");
    var token = botao.getAttribute("data-token");

    caixa.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
    botao.textContent = confirmar ? "Gravando..." : "Cancelando...";

    fetch(confirmar ? "/api/confirmar" : "/api/cancelar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: token })
    })
      .then(function (r) {
        if (r.status === 401) { window.location.href = "/entrar"; return null; }
        return r.json();
      })
      .then(function (d) {
        if (!d) return;
        caixa.remove();
        addResposta(d);
      })
      .catch(function (erro) {
        caixa.querySelectorAll("button").forEach(function (b) { b.disabled = false; });
        botao.textContent = confirmar ? "Confirmar e gravar" : "Cancelar";
        addResposta({
          tipo: "erro", titulo: "Não deu certo",
          texto: "Não consegui falar com o servidor: " + erro.message
        });
      });
  });

  function perguntar(texto) {
    addUsuario(texto);
    var pensando = addPensando();
    enviar.disabled = true;

    fetch("/api/perguntar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto: texto })
    })
      .then(function (r) {
        if (r.status === 401) { window.location.href = "/entrar"; return null; }
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (dados) {
        /* Tirar os pontinhos SEMPRE, inclusive quando nao veio resposta.
           Antes, o caminho sem dados deixava a animacao girando para sempre e
           o chat parecia travado. */
        removerPensando(pensando);
        if (!dados) return;
        addResposta(dados);
      })
      .catch(function (erro) {
        removerPensando(pensando);
        addResposta({
          tipo: "erro",
          titulo: "Não deu certo",
          texto: "Não consegui falar com o servidor. Verifique a conexão e tente de novo. (" + erro.message + ")"
        });
      })
      .finally(function () {
        enviar.disabled = false;
        entrada.focus();
      });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var texto = entrada.value.trim();
    if (!texto) return;
    entrada.value = "";
    entrada.style.height = "auto";
    perguntar(texto);
  });

  entrada.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      /* requestSubmit dispara um submit real e cancelavel, ao contrario de
         dispatchEvent(new Event("submit")), onde preventDefault nao pega. */
      if (form.requestSubmit) form.requestSubmit();
      else form.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });

  entrada.addEventListener("input", function () {
    entrada.style.height = "auto";
    entrada.style.height = Math.min(entrada.scrollHeight, 180) + "px";
  });

  /* sugestoes */
  fetch("/api/sugestoes")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (dados) {
      if (!dados) return;
      var caixa = document.getElementById("sugestoes");
      if (!caixa) return;
      dados.sugestoes.forEach(function (s) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "sugestao";
        b.textContent = s;
        b.addEventListener("click", function () { perguntar(s); });
        caixa.appendChild(b);
      });
    })
    .catch(function () { });

  /* painel de fontes */
  function abrirPainel(estado) {
    var arquivos = estado.arquivos || {};
    var nomes = Object.keys(arquivos);

    var html = "<dl>";
    html += "<dt>Modo</dt><dd>Somente leitura. Nenhum arquivo é alterado.</dd>";
    html += "<dt>Interpretação</dt><dd>" + esc(estado.fornecedor || "-") + "</dd>";
    html += "<dt>Carregado em</dt><dd>" + esc(estado.carregado_em || "-") + "</dd>";
    html += "<dt>Registros lidos</dt><dd>" +
      esc(estado.notas || 0) + " notas · " + esc(estado.lancamentos || 0) +
      " lançamentos · " + esc(estado.lotes || 0) + " lotes · " +
      esc(estado.manuais || 0) + " reembolsos manuais · " +
      esc(estado.notas_debito || 0) + " notas de débito</dd>";
    html += "<dt>Arquivos</dt><dd>";
    if (nomes.length) {
      nomes.forEach(function (a) {
        html += esc(a) + " <span style='color:var(--tinta-3)'>(salvo em " +
          esc(arquivos[a]) + ")</span><br>";
      });
    } else {
      html += 'Nenhuma planilha carregada. <a href="/planilhas">Enviar agora</a>';
    }
    html += "</dd></dl>";

    if (estado.avisos && estado.avisos.length) {
      html += "<h2>Integridade das fontes</h2>";
      estado.avisos.forEach(function (a) {
        var cls = a.severidade === "critico" ? " critico" : "";
        html += '<div class="aviso' + cls + '"><span class="icone">!</span><span><b>' +
          esc(a.aba || a.arquivo) + "</b><br>" + esc(a.mensagem) + "</span></div>";
      });
    }
    painelCorpo.innerHTML = html;
    painel.hidden = false;
  }

  function falhaNoPainel(mensagem) {
    painelCorpo.innerHTML = '<div class="aviso critico"><span class="icone">!</span>' +
      "<span>" + esc(mensagem) + "</span></div>";
    painel.hidden = false;
  }

  document.getElementById("btn-estado").addEventListener("click", function () {
    fetch("/api/estado")
      .then(function (r) {
        if (r.status === 401) { window.location.href = "/entrar"; return null; }
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (estado) { if (estado) abrirPainel(estado); })
      .catch(function (erro) {
        falhaNoPainel("Não consegui ler o estado das fontes: " + erro.message);
      });
  });

  document.getElementById("btn-fechar-painel").addEventListener("click", function () {
    painel.hidden = true;
  });

  painel.addEventListener("click", function (e) {
    if (e.target === painel) painel.hidden = true;
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !painel.hidden) painel.hidden = true;
  });

  document.getElementById("btn-recarregar").addEventListener("click", function () {
    var b = this;
    b.disabled = true;
    b.textContent = "Recarregando";
    fetch("/api/recarregar", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (estado) {
        b.textContent = "Recarregar";
        b.disabled = false;
        abrirPainel(estado);
      })
      .catch(function () {
        b.textContent = "Recarregar";
        b.disabled = false;
      });
  });

  entrada.focus();
})();
