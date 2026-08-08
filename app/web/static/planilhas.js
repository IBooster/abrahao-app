/* Envio das planilhas. O servidor confere cada arquivo antes de substituir. */
(function () {
  "use strict";

  var zona = document.getElementById("zona");
  var entrada = document.getElementById("entrada-arquivo");
  var lista = document.getElementById("lista");
  var progresso = document.getElementById("progresso");
  var alerta = document.getElementById("alerta");
  var histBox = document.getElementById("historico");
  var pastaBox = document.getElementById("pasta");

  function esc(t) {
    return String(t == null ? "" : t)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function carregar() {
    fetch("/api/planilhas")
      .then(function (r) {
        if (r.status === 401) { window.location.href = "/entrar"; return null; }
        return r.json();
      })
      .then(function (d) {
        if (!d) return;
        desenhar(d);
      })
      .catch(function () {
        lista.innerHTML = '<p class="carregando">Não consegui ler a situação dos arquivos.</p>';
      });
  }

  function desenhar(d) {
    var html = "";
    d.arquivos.forEach(function (a) {
      html += '<div class="arquivo' + (a.presente ? " ok" : " falta") + '">';
      html += '<div class="arquivo-info">';
      html += '<span class="arquivo-rotulo">' + esc(a.rotulo) + "</span>";
      html += '<span class="arquivo-desc">' + esc(a.descricao) + "</span>";
      html += '<span class="arquivo-nome">' + esc(a.nome) + "</span>";
      html += "</div>";
      html += '<div class="arquivo-estado">';
      if (a.presente) {
        html += '<span class="selo-ok">no servidor</span>';
        html += '<span class="arquivo-meta">' + esc(a.tamanho) + " · " + esc(a.atualizado_em) + "</span>";
      } else {
        html += '<span class="selo-falta">faltando</span>';
      }
      html += "</div></div>";
    });
    lista.innerHTML = html;

    if (d.faltando.length === 0) {
      alerta.innerHTML = '<div class="faixa ok">Os cinco arquivos estão no servidor. ' +
        'O chat já pode responder. <a href="/">Ir para o chat</a></div>';
    } else {
      alerta.innerHTML = '<div class="faixa falta"><b>' + d.faltando.length +
        " arquivo(s) faltando.</b> O chat não consegue responder até que todos cheguem.</div>";
    }

    if (d.historico && d.historico.length) {
      var h = '<div class="tabela-wrap"><table class="linhas-tab"><tbody>';
      d.historico.forEach(function (e) {
        h += "<tr><td>";
        h += '<span class="rotulo">' + esc(e.arquivo) + "</span>";
        h += '<span class="detalhe">' + esc(e.quando.replace("T", " ")) +
          " · " + esc(e.usuario) +
          (e.substituiu_versao_anterior ? " · substituiu a versão anterior" : " · primeiro envio") +
          (e.backup ? " · cópia guardada" : "") + "</span>";
        h += "</td><td class=\"valor\">" + esc(e.abas) + " abas</td></tr>";
      });
      histBox.innerHTML = h + "</tbody></table></div>";
    } else {
      histBox.innerHTML = '<p class="carregando">Nenhum envio ainda.</p>';
    }

    pastaBox.textContent = "Pasta no servidor: " + d.pasta;
  }

  function enviar(arquivos) {
    if (!arquivos || !arquivos.length) return;
    progresso.innerHTML = "";

    var fila = Array.prototype.slice.call(arquivos);
    var restantes = fila.length;

    fila.forEach(function (f) {
      var linha = document.createElement("div");
      linha.className = "envio";
      linha.innerHTML = '<span class="envio-nome">' + esc(f.name) + "</span>" +
        '<span class="envio-estado">enviando...</span>';
      progresso.appendChild(linha);

      var dados = new FormData();
      dados.append("arquivo", f);

      fetch("/api/planilhas", { method: "POST", body: dados })
        .then(function (r) {
          if (r.status === 401) { window.location.href = "/entrar"; return null; }
          return r.json();
        })
        .then(function (d) {
          if (!d) return;
          var estado = linha.querySelector(".envio-estado");
          if (d.ok) {
            linha.className = "envio ok";
            estado.textContent = d.substituiu
              ? "substituído (" + d.abas + " abas, cópia guardada)"
              : "recebido (" + d.abas + " abas)";
          } else {
            linha.className = "envio erro";
            estado.textContent = d.erro;
          }
        })
        .catch(function (erro) {
          linha.className = "envio erro";
          linha.querySelector(".envio-estado").textContent =
            "falhou: " + erro.message;
        })
        .finally(function () {
          restantes -= 1;
          if (restantes === 0) carregar();
        });
    });
  }

  entrada.addEventListener("change", function () {
    enviar(entrada.files);
    entrada.value = "";
  });

  ["dragenter", "dragover"].forEach(function (evento) {
    zona.addEventListener(evento, function (e) {
      e.preventDefault();
      zona.classList.add("arrastando");
    });
  });

  ["dragleave", "drop"].forEach(function (evento) {
    zona.addEventListener(evento, function (e) {
      e.preventDefault();
      if (evento === "dragleave" && zona.contains(e.relatedTarget)) return;
      zona.classList.remove("arrastando");
    });
  });

  zona.addEventListener("drop", function (e) {
    enviar(e.dataTransfer.files);
  });

  carregar();
})();
