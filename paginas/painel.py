"""Painel ao vivo: faturamento de cada atendente contra a meta do período.

Animação: na primeira carga as barras crescem do zero e os totais contam até
o valor; depois, a cada atualização, só o que mudou se move (do valor anterior
para o atual). Os valores anteriores ficam em st.session_state["animacao"].

Modo TV (/?tv=1, opcional &regiao=para): tela única, sem barra lateral nem
rolagem, proporcional à altura da tela; usa sempre o período em andamento.
"""
import time
import unicodedata
from html import escape
from pathlib import Path
from urllib.parse import quote

import altair as alt
import pandas as pd
import streamlit as st

import banco_local
import fonte
from formatos import brl, data_hora, inteiro, nome_regiao, periodo, rotulo_campanha

ATUALIZAR_A_CADA = 60  # segundos
AZUL = "#28347c"
TINTA_2 = "#5b6078"
TODAS = "Todas"
TV_MAX_RANKING = 18  # o que cabe em duas colunas numa tela 16:9
TV_ULTIMOS = 5

# Conta os números marcados com data-contar de data-de até o valor final. Fica
# num bloco próprio, sem dado nenhum do banco, porque é o único com JavaScript.
_CONTADOR = """<script>/* __N__ */
(() => {
  const parado = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fmt = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
  document.querySelectorAll("[data-contar]:not([data-contado])").forEach((el) => {
    el.dataset.contado = "1";
    const de = Number(el.dataset.de), para = Number(el.dataset.contar);
    const moeda = el.dataset.moeda === "1";
    const escrever = (v) => {
      const n = fmt.format(Math.round(v));
      el.textContent = moeda ? "R$\\u00a0" + n : n + "%";
    };
    if (parado || de === para) return escrever(para);
    const t0 = performance.now(), dur = 1100;
    escrever(de);
    const quadro = (t) => {
      const k = Math.min((t - t0) / dur, 1);
      escrever(de + (para - de) * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(quadro);
    };
    requestAnimationFrame(quadro);
  });
})();
</script>"""


@st.cache_data(ttl=45, show_spinner=False)
def _carregar(ini_utc, fim_utc, user_ids, tipos, excluidos):
    # Cache curto: várias abas abertas fazem uma consulta só ao banco de produção.
    return fonte.dados_painel(ini_utc, fim_utc, user_ids, tipos, excluidos)


@st.cache_data(ttl=600, show_spinner=False)
def _regioes(user_ids, desde_utc):
    df = fonte.regioes_atendentes(user_ids, desde_utc)
    return dict(zip(df["user_id"], df["nome_empresa"].map(nome_regiao)))


def regioes_da_campanha(campanha, metas):
    """user_id -> região. Olha o período e os 60 dias antes de agora."""
    desde = min(campanha["inicio"], fonte.agora_local() - pd.Timedelta(days=60))
    desde = fonte.para_utc(desde).replace(minute=0, second=0, microsecond=0)  # estável p/ o cache
    regioes = _regioes(tuple(m["user_id"] for m in metas), desde)
    return {m["user_id"]: regioes.get(m["user_id"], nome_regiao(None)) for m in metas}


def _sem_acento(texto):
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in base if not unicodedata.combining(c)).strip().lower()


def _montar_tabela(metas, dados, regioes):
    df = pd.DataFrame(metas)[["user_id", "nome", "valor_meta"]]
    df["regiao"] = df["user_id"].map(regioes)
    df = df.merge(dados["resumo"], on="user_id", how="left")
    df = df.merge(dados["novos"], on="user_id", how="left")
    numeros = ["pedidos", "faturamento", "clientes", "novos"]
    df[numeros] = df[numeros].astype(float).fillna(0)
    df["atingido"] = (df["faturamento"] / df["valor_meta"].where(df["valor_meta"] > 0) * 100).fillna(0)
    return df.sort_values(["atingido", "faturamento"], ascending=False).reset_index(drop=True)


def _por_regiao(df):
    por = (
        df.groupby("regiao")
        .agg(faturamento=("faturamento", "sum"), meta=("valor_meta", "sum"), atendentes=("user_id", "count"))
        .sort_values("faturamento", ascending=False)
    )
    por["pct"] = (por["faturamento"] / por["meta"].where(por["meta"] > 0) * 100).fillna(0)
    return por


# --- Peças animadas ----------------------------------------------------------

def _barra(de, para, atraso=0.0):
    """Preenchimento que cresce de `de` até `para` (em %)."""
    return (
        f'<div class="anima" style="--de:{min(de, 100):.1f}%;--para:{min(para, 100):.1f}%;'
        f'--atraso:{atraso:.2f}s"></div>'
    )


def _contador(valor, de, moeda=True):
    """Número que conta de `de` até `valor`.

    Sai escrito com o valor de partida (o que já estava na tela), para não
    piscar o valor final antes da contagem começar.
    """
    texto = brl(de, centavos=False) if moeda else f"{de:.0f}%"
    return (
        f'<span data-contar="{valor:.0f}" data-de="{de:.0f}" data-moeda="{int(moeda)}">{texto}</span>'
    )


def _animar_numeros():
    # O comentário muda a cada chamada para o bloco ser recriado e o script rodar.
    st.html(_CONTADOR.replace("__N__", str(time.time_ns())), unsafe_allow_javascript=True)


def _juntar(nomes):
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _comemorar(antes, df, por_regiao, pct_total, regiao):
    """Frase para quem passou de 100% desde a última atualização (None se ninguém)."""
    if antes is None:
        return None
    if regiao == TODAS and antes["pct"] < 100 <= pct_total:
        return "Meta geral batida!"
    # Quem não estava na memória (entrou agora na meta) não conta como "bateu agora".
    regioes = [
        nome for nome, r in por_regiao.iterrows()
        if antes["regioes"].get(nome, {}).get("pct", 100) < 100 <= r.pct
    ]
    if regioes:
        return f"{_juntar(regioes)} {'bateu' if len(regioes) == 1 else 'bateram'} a meta!"
    pessoas = [
        r.nome for r in df.itertuples()
        if antes["atend"].get(r.user_id, {}).get("pct", 100) < 100 <= r.atingido
    ]
    if pessoas:
        return f"{_juntar(pessoas)} {'bateu' if len(pessoas) == 1 else 'bateram'} a meta!"
    return None


# --- Blocos do painel (cada um devolve HTML) ---------------------------------

def _html_hero(df, campanha, agora, regiao, antes, festa, tv):
    meta = df["valor_meta"].sum()
    faturado = df["faturamento"].sum()
    pedidos = df["pedidos"].sum()
    pct = faturado / meta * 100 if meta else 0

    inicio, fim = campanha["inicio"], campanha["fim"]
    if agora < inicio:
        situacao = f"Começa em {data_hora(inicio)}"
    elif fim is not None and agora >= fim:
        situacao = "Encerrado"
    else:
        situacao = f"Atualizado às {agora:%H:%M}"

    numeros = [
        ("Pedidos", inteiro(pedidos)),
        ("Ticket médio", brl(faturado / pedidos if pedidos else 0, centavos=False)),
        ("Clientes novos", inteiro(df["novos"].sum())),
    ]
    if faturado < meta:
        numeros.append(("Falta", brl(meta - faturado, centavos=False)))
    if fim is not None and inicio < agora < fim and faturado:
        decorrido = (agora - inicio) / (fim - inicio)
        numeros.append(("No ritmo atual", brl(faturado / decorrido, centavos=False)))

    itens = "".join(f"<div>{rotulo}<b class='num'>{valor}</b></div>" for rotulo, valor in numeros)
    selo = "" if regiao == TODAS else f"<span class='hero-regiao'>{escape(regiao)}</span>"
    faixa = (
        f"<div class='festa' role='status'><div class='festa-a' aria-hidden='true'></div>"
        f"<strong>{escape(festa)}</strong></div>"
        if festa else ""
    )
    logo = "<div class='hero-logo' role='img' aria-label='Adrilar'></div>" if tv else ""
    fat_antes, pct_antes = (antes["total"], antes["pct"]) if antes else (0, 0)
    html = f"""
        <section class="hero">
          <div class="hero-a" aria-hidden="true"></div>
          {faixa}
          <div class="hero-topo">
            <div>
              <h1>{escape(campanha["nome"])}{selo}</h1>
              <span class="hero-periodo">{periodo(campanha).capitalize()}</span>
            </div>
            <div class="hero-canto">{logo}<span class="hero-hora">{situacao}</span></div>
          </div>
          <div class="hero-placar">
            <span class="hero-valor num">{_contador(faturado, fat_antes)}</span>
            <span class="hero-de num">de {brl(meta, centavos=False)}</span>
            <span class="hero-pct num">{_contador(pct, pct_antes, moeda=False)}</span>
          </div>
          <div class="hero-barra">{_barra(pct_antes, pct)}</div>
          <div class="hero-numeros">{itens}</div>
        </section>
    """
    return html, faturado, pct


def _html_regioes(por_regiao, selecionada, antes):
    blocos = []
    for i, (regiao, r) in enumerate(por_regiao.iterrows()):
        classes = ["regiao"]
        if r.pct >= 100:
            classes.append("batida")
        if selecionada != TODAS:
            classes.append("ativa" if regiao == selecionada else "apagada")
        anterior = antes["regioes"].get(regiao, {}) if antes else {}
        atraso = 0 if antes else 0.15 + i * 0.06
        n = int(r.atendentes)
        blocos.append(
            f"""<div class="{' '.join(classes)}">
              <span class="regiao-nome">{escape(regiao)}</span>
              <span class="regiao-valor num">{_contador(r.faturamento, anterior.get('fat', 0))}</span>
              <span class="regiao-meta num">de {brl(r.meta, centavos=False)}</span>
              <div class="trilho">{_barra(anterior.get('pct', 0), r.pct, atraso)}</div>
              <span class="regiao-rodape"><b class="num">{r.pct:.0f}%</b><span>{n} atendente{'s' if n != 1 else ''}</span></span>
            </div>"""
        )
    return f"<div class='regioes'>{''.join(blocos)}</div>"


def _html_ranking(df, antes, limite=None):
    linhas = []
    visiveis = df if limite is None else df.head(limite)
    for pos, r in enumerate(visiveis.itertuples(), start=1):
        anterior = antes["atend"].get(r.user_id, {}) if antes else {}
        batida = r.atingido >= 100
        selo = "<span class='selo'>meta batida</span>" if batida else ""
        subiu = anterior.get("pos", pos) > pos
        seta = f"<i class='subiu' title='Subiu {anterior['pos'] - pos}'>▲</i>" if subiu else ""
        atraso = 0 if antes else 0.25 + pos * 0.035
        linhas.append(
            f"""<li class="{'batida' if batida else ''}">
              <span class="pos num">{pos}{seta}</span>
              <span class="nome">{escape(r.nome)}{selo}</span>
              <span class="valor num">{brl(r.faturamento, centavos=False)}<small>de {brl(r.valor_meta, centavos=False)}</small></span>
              <span class="pct num">{r.atingido:.0f}%</span>
              <div class="trilho">{_barra(anterior.get('pct', 0), r.atingido, atraso)}</div>
            </li>"""
        )
    resto = len(df) - len(visiveis)
    mais = f"<p class='vazio'>e mais {resto}</p>" if resto > 0 else ""
    # Muitas atendentes: duas colunas (o CSS só usa isso no modo TV).
    colunas = " duas" if len(visiveis) > 8 else ""
    return f"<h2 class='secao'>Ranking</h2><ol class='ranking{colunas}'>{''.join(linhas)}</ol>{mais}"


def _html_ultimos(ultimos, nomes, antes, limite=None):
    if ultimos.empty:
        corpo = "<p class='vazio'>Nenhum pedido ainda.</p>"
    else:
        visto = antes["ultimo_id"] if antes else None
        linhas = ultimos if limite is None else ultimos.head(limite)
        corpo = "<ul class='feed'>" + "".join(
            f"<li class='{'novo' if visto is not None and r.id > visto else ''}'>"
            f"<time class='num'>{r.data:%H:%M}</time>"
            f"<span>{escape(nomes.get(r.user_id, ''))}</span>"
            f"<b class='num'>{brl(r.valor_total, centavos=False)}</b></li>"
            for r in linhas.itertuples()
        ) + "</ul>"
    return f"<h2 class='secao'>Últimos pedidos</h2>{corpo}"


def _serie_horas(por_hora, campanha, agora):
    """Faturamento por hora (ou dia) no período todo, com zero onde não houve pedido.

    O eixo cobre o período inteiro (sem término: até agora), para a live
    aparecer completa e uma hora só não virar um bloco.
    """
    inicio = campanha["inicio"]
    fim = campanha["fim"] - pd.Timedelta(microseconds=1) if campanha["fim"] else agora
    fim = max(fim, por_hora["hora"].max())
    varios_dias = fim - inicio > pd.Timedelta(days=2)
    passo = "D" if varios_dias else "h"
    dados = por_hora.assign(hora=por_hora["hora"].dt.floor(passo))
    dados = dados.groupby("hora")[["pedidos", "faturamento"]].sum()
    eixo = pd.date_range(
        pd.Timestamp(inicio).floor(passo), pd.Timestamp(fim).floor(passo), freq=passo, name="hora"
    )
    dados = dados.reindex(eixo, fill_value=0).reset_index()
    if varios_dias:
        formato = "%d/%m"
    else:
        formato = "%Hh" if fim - inicio < pd.Timedelta(hours=24) else "%d/%m %Hh"
    dados["quando"] = dados["hora"].dt.strftime(formato)
    return dados, varios_dias


def _grafico_horas(por_hora, campanha, agora):
    st.html("<h2 class='secao'>Faturamento por hora</h2>")
    if por_hora.empty:
        st.html("<p class='vazio'>Nenhum pedido ainda.</p>")
        return
    dados, varios_dias = _serie_horas(por_hora, campanha, agora)
    dados["fat_txt"] = dados["faturamento"].map(brl)
    grafico = (
        alt.Chart(dados)
        .mark_bar(color=AZUL, cornerRadiusEnd=4)
        .encode(
            x=alt.X("quando:N", sort=None, title=None, axis=alt.Axis(labelAngle=0, ticks=False, domain=False)),
            y=alt.Y(
                "faturamento:Q",
                title=None,
                axis=alt.Axis(
                    tickCount=4,
                    domain=False,
                    ticks=False,
                    labelExpr="datum.value >= 1000 ? format(datum.value / 1000, ',.0f') + ' mil' : datum.value",
                ),
            ),
            tooltip=[
                alt.Tooltip("quando:N", title="Dia" if varios_dias else "Hora"),
                alt.Tooltip("fat_txt:N", title="Faturamento"),
                alt.Tooltip("pedidos:Q", title="Pedidos"),
            ],
        )
        .properties(height=200)
        .configure_axis(labelColor=TINTA_2, gridColor="#eceef5")
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(grafico, width="stretch")


def _html_horas(por_hora, campanha, agora, antes):
    """Versão compacta do gráfico por hora, em HTML, para o modo TV."""
    titulo = "<h2 class='secao'>Faturamento por hora</h2>"
    if por_hora.empty:
        return titulo + "<p class='vazio'>Nenhum pedido ainda.</p>"
    dados, _ = _serie_horas(por_hora, campanha, agora)
    maior = dados["faturamento"].max() or 1
    pico = dados["faturamento"].idxmax()
    pular = max(1, -(-len(dados) // 9))  # no máximo uns 9 rótulos no eixo
    barras = []
    for i, r in enumerate(dados.itertuples()):
        valor = f"<em class='num'>{brl(r.faturamento, centavos=False)}</em>" if i == pico and r.faturamento else ""
        rotulo = r.quando if i % pular == 0 else ""
        barras.append(
            f"<div class='hora' title='{r.quando}: {brl(r.faturamento, centavos=False)}'>"
            f"<div class='coluna'><i class='{'' if r.faturamento else 'zero'}' "
            f"style='height:{r.faturamento / maior * 100:.1f}%'>{valor}</i></div>"
            f"<span>{rotulo}</span></div>"
        )
    entrada = "" if antes else " entrada"
    return f"{titulo}<div class='horas{entrada}'>{''.join(barras)}</div>"


# --- Painel ------------------------------------------------------------------

def _regiao_pedida(texto, regioes):
    """Casa o ?regiao= da URL com o nome da região, sem ligar para acento ou caixa."""
    alvo = _sem_acento(texto)
    return next((r for r in sorted(set(regioes.values())) if _sem_acento(r) == alvo), TODAS)


@st.fragment(run_every=ATUALIZAR_A_CADA)
def painel(campanha_id, regiao, tv=False):
    if campanha_id is None:
        # Modo TV: o período em andamento, reavaliado a cada ciclo.
        campanha = banco_local.campanha_atual(banco_local.listar_campanhas(), fonte.agora_local())
    else:
        # Relê a configuração a cada ciclo para pegar mudanças feitas em outra aba.
        campanha = banco_local.obter_campanha(campanha_id)
    if campanha is None:
        st.warning("Nenhum período de meta." if campanha_id is None else "Este período foi excluído.")
        return
    metas = banco_local.listar_metas(campanha["id"])
    if not metas:
        st.title(campanha["nome"])
        st.html("<p class='vazio'>Nenhuma atendente neste período.</p>")
        if not tv:
            st.page_link("paginas/configuracao.py", label="Cadastrar atendentes", icon=":material/tune:")
        return

    filtro = (
        fonte.para_utc(campanha["inicio"]),
        fonte.para_utc(campanha["fim"]) if campanha["fim"] else None,
    )
    regras = (tuple(campanha["tipos_pedido"]), tuple(campanha["status_excluidos"]))
    todas_ids = tuple(m["user_id"] for m in metas)
    try:
        regioes = regioes_da_campanha(campanha, metas)
        if tv:
            regiao = _regiao_pedida(regiao, regioes)
        dados_todos = _carregar(*filtro, todas_ids, *regras)
        df_todos = _montar_tabela(metas, dados_todos, regioes)
        if regiao in set(regioes.values()):
            # Ranking e números vêm do total; pedidos e horas são recarregados
            # só com as atendentes da região.
            dados = _carregar(*filtro, tuple(u for u in todas_ids if regioes[u] == regiao), *regras)
            df = df_todos[df_todos["regiao"] == regiao]
        else:
            regiao, dados, df = TODAS, dados_todos, df_todos
    except Exception as erro:
        st.error(f"Sem conexão com o banco de pedidos: {erro}")
        return

    chave = (campanha["id"], regiao, tv)
    memoria = st.session_state.setdefault("animacao", {})
    antes = memoria.get(chave)
    por_regiao = _por_regiao(df_todos)
    meta_total = df["valor_meta"].sum()
    pct_total = df["faturamento"].sum() / meta_total * 100 if meta_total else 0
    festa = _comemorar(antes, df, por_regiao, pct_total, regiao)

    agora = fonte.agora_local()
    nomes = dict(zip(df["user_id"], df["nome"]))
    hero, faturado, pct = _html_hero(df, campanha, agora, regiao, antes, festa, tv)
    quadro = _html_regioes(por_regiao, regiao, antes) if len(por_regiao) > 1 else ""

    if tv:
        st.html(
            f"""<div class="tela">
              {hero}
              {quadro}
              <div class="tela-baixo">
                <div class="tela-ranking">{_html_ranking(df, antes, TV_MAX_RANKING)}</div>
                <div class="tela-lado">
                  <div>{_html_ultimos(dados["ultimos"], nomes, antes, TV_ULTIMOS)}</div>
                  <div class="lado-horas">{_html_horas(dados["por_hora"], campanha, agora, antes)}</div>
                </div>
              </div>
            </div>"""
        )
        _animar_numeros()
    else:
        st.html(hero)
        _animar_numeros()
        if quadro:
            st.html(quadro)
            _animar_numeros()
        esquerda, direita = st.columns([2, 1], gap="large")
        with esquerda:
            st.html(_html_ranking(df, antes))
        with direita:
            st.html(_html_ultimos(dados["ultimos"], nomes, antes))
        _grafico_horas(dados["por_hora"], campanha, agora)

    ultimos_ids = dados["ultimos"]["id"]
    memoria[chave] = {
        "total": faturado,
        "pct": pct,
        "atend": {
            r.user_id: {"pct": r.atingido, "pos": pos}
            for pos, r in enumerate(df.itertuples(), start=1)
        },
        "regioes": {nome: {"fat": r.faturamento, "pct": r.pct} for nome, r in por_regiao.iterrows()},
        "ultimo_id": int(ultimos_ids.max()) if len(ultimos_ids) else (antes or {}).get("ultimo_id", 0),
    }


if st.query_params.get("tv", "0") not in ("", "0"):
    st.html(Path(__file__).parents[1] / "tv.css")
    painel(None, st.query_params.get("regiao", ""), tv=True)
    st.stop()

campanhas = banco_local.listar_campanhas()
if not campanhas:
    st.title("Metas Live Shop")
    st.html("<p class='vazio'>Nenhum período de meta ainda.</p>")
    st.page_link("paginas/configuracao.py", label="Criar período", icon=":material/tune:")
    st.stop()

por_id = {c["id"]: c for c in campanhas}
if st.session_state.get("campanha_painel") not in por_id:
    st.session_state["campanha_painel"] = banco_local.campanha_atual(campanhas, fonte.agora_local())["id"]

with st.sidebar:
    escolhida = st.selectbox(
        "Período",
        list(por_id),
        key="campanha_painel",
        format_func=lambda i: rotulo_campanha(por_id[i]),
    )
    metas_escolhida = banco_local.listar_metas(escolhida)
    try:
        nomes_regioes = sorted(set(regioes_da_campanha(por_id[escolhida], metas_escolhida).values()))
    except Exception:
        nomes_regioes = []  # sem banco: o painel mostra o erro
    regiao = TODAS
    if len(nomes_regioes) > 1:
        opcoes = [TODAS] + nomes_regioes
        if st.session_state.get("regiao_painel") not in opcoes:
            st.session_state["regiao_painel"] = TODAS
        regiao = st.pills("Região", opcoes, key="regiao_painel", required=True)
    if st.button("Atualizar", icon=":material/refresh:"):
        _carregar.clear()
        _regioes.clear()
    endereco_tv = "/?tv=1" + ("" if regiao == TODAS else "&regiao=" + quote(_sem_acento(regiao)))
    st.link_button("Abrir modo TV", endereco_tv, icon=":material/tv:")

painel(escolhida, regiao)
