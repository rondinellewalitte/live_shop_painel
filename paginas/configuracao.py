"""Configuração: período da meta e atendentes participantes com o valor de cada uma."""
import hmac
import os
from datetime import datetime

import pandas as pd
import streamlit as st

import banco_local
import fonte  # importa conexao.py, que carrega o .env
from formatos import brl, rotulo_campanha

NOVA = 0


def _exigir_senha():
    """Bloqueia a página até digitarem a SENHA_CONFIG do .env.

    O bloqueio precisa ficar aqui dentro: a página abre direto pela URL
    /configuracao, mesmo que saísse do menu.
    """
    senha = os.getenv("SENHA_CONFIG")
    if not senha:
        st.warning("Tela sem senha. Defina `SENHA_CONFIG` no `.env` e reinicie o app.")
        return
    if st.session_state.get("config_liberada"):
        if st.sidebar.button("Sair", icon=":material/logout:"):
            st.session_state["config_liberada"] = False
            st.rerun()
        return

    st.title("Configurar metas")
    with st.form("form_senha"):
        digitada = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar", type="primary")
    # Compara bytes: compare_digest recusa str com acento (ç, ã...).
    if entrar and hmac.compare_digest(digitada.encode("utf-8"), senha.encode("utf-8")):
        st.session_state["config_liberada"] = True
        st.rerun()
    if entrar:
        st.error("Senha incorreta.")
    st.stop()


_exigir_senha()


@st.cache_data(ttl=3600, show_spinner=False)
def _opcoes_pedido():
    return fonte.opcoes_pedido()


@st.cache_data(ttl=600, show_spinner=False)
def _usuarios(somente_atendentes):
    return fonte.usuarios(somente_atendentes=somente_atendentes)


def _opcoes(*listas):
    return sorted(set().union(*listas))


def _concluir(aviso, campanha_id=None):
    st.session_state["aviso_cfg"] = aviso
    st.session_state["ir_para_campanha"] = campanha_id
    st.rerun()


st.title("Configurar metas")

if aviso := st.session_state.pop("aviso_cfg", None):
    st.toast(aviso, icon=":material/check:")

try:
    tipos_banco, status_banco = _opcoes_pedido()
except Exception:
    tipos_banco, status_banco = [], []

campanhas = banco_local.listar_campanhas()
por_id = {c["id"]: c for c in campanhas}
opcoes = [c["id"] for c in campanhas] + [NOVA]

if "ir_para_campanha" in st.session_state:
    st.session_state["campanha_cfg"] = st.session_state.pop("ir_para_campanha")
if st.session_state.get("campanha_cfg") not in opcoes:
    atual = banco_local.campanha_atual(campanhas, fonte.agora_local())
    st.session_state["campanha_cfg"] = atual["id"] if atual else NOVA

sel = st.selectbox(
    "Período",
    opcoes,
    key="campanha_cfg",
    format_func=lambda i: "Novo período" if i == NOVA else rotulo_campanha(por_id[i]),
)
campanha = por_id.get(sel)

# --- Período ---------------------------------------------------------------
agora = fonte.agora_local()
padrao_ini = campanha["inicio"] if campanha else agora.replace(minute=0, second=0, microsecond=0)
padrao_fim = (campanha or {}).get("fim") or padrao_ini.replace(hour=23, minute=59)
tipos_atuais = campanha["tipos_pedido"] if campanha else banco_local.TIPOS_PADRAO
excl_atuais = campanha["status_excluidos"] if campanha else banco_local.STATUS_EXCLUIDOS_PADRAO

with st.form(f"form_campanha_{sel}", border=False):
    nome = st.text_input("Nome", value=campanha["nome"] if campanha else f"Live {agora:%d/%m}")
    c1, c2, c3, c4 = st.columns(4)
    dia_ini = c1.date_input("Início", padrao_ini.date(), format="DD/MM/YYYY")
    hora_ini = c2.time_input(
        "Hora", padrao_ini.time(), step=60, help="Horário de Brasília", key=f"hora_ini_{sel}"
    )
    dia_fim = c3.date_input("Término", padrao_fim.date(), format="DD/MM/YYYY")
    hora_fim = c4.time_input(
        "Hora", padrao_fim.time(), step=60, help="Horário de Brasília", key=f"hora_fim_{sel}"
    )
    sem_fim = st.checkbox("Sem término", value=campanha is not None and campanha["fim"] is None)
    with st.expander("O que conta para a meta"):
        tipos = st.multiselect(
            "Tipos de pedido",
            _opcoes(tipos_banco, banco_local.TIPOS_PADRAO, tipos_atuais),
            default=tipos_atuais,
        )
        excluidos = st.multiselect(
            "Status ignorados",
            _opcoes(status_banco, banco_local.STATUS_EXCLUIDOS_PADRAO, excl_atuais),
            default=excl_atuais,
        )
    enviar = st.form_submit_button("Salvar período" if campanha else "Criar período", type="primary")

if enviar:
    inicio = datetime.combine(dia_ini, hora_ini)
    fim = None if sem_fim else datetime.combine(dia_fim, hora_fim)
    erros = []
    if not nome.strip():
        erros.append("Informe o nome.")
    if not tipos:
        erros.append("Escolha pelo menos um tipo de pedido.")
    if fim is not None and fim <= inicio:
        erros.append("O término precisa ser depois do início.")
    for e in erros:
        st.error(e)
    if not erros:
        novo_id = banco_local.salvar_campanha(
            nome, inicio, fim, tipos, excluidos, campanha_id=campanha["id"] if campanha else None
        )
        _concluir("Período salvo." if campanha else "Período criado.", novo_id)

if campanha is None:
    st.stop()

# --- Atendentes ------------------------------------------------------------
st.subheader("Atendentes")

metas = banco_local.listar_metas(campanha["id"])
ja_cadastradas = {m["user_id"] for m in metas}

todos = st.toggle("Incluir todos os usuários", help="Por padrão, só quem lançou pedido nos últimos 60 dias.")
try:
    usuarios = _usuarios(not todos)
except Exception as erro:
    st.error(f"Sem conexão com o banco de usuários: {erro}")
    usuarios = pd.DataFrame(columns=["user_id", "username", "nome", "pedidos"])

disponiveis = usuarios[~usuarios["user_id"].isin(ja_cadastradas)].set_index("user_id")
rotulos = {uid: f"{u.nome} ({u.username})" for uid, u in disponiveis.iterrows()}

with st.form(f"form_metas_{campanha['id']}", clear_on_submit=True, border=False):
    c1, c2, c3 = st.columns([3, 1, 1], vertical_alignment="bottom")
    escolhidas = c1.multiselect(
        "Atendente",
        list(rotulos),
        format_func=rotulos.get,
        placeholder="Escolha uma ou mais",
    )
    valor = c2.number_input("Meta (R$)", min_value=0.0, step=500.0, format="%.2f")
    adicionar = c3.form_submit_button("Adicionar", type="primary", width="stretch")

if adicionar:
    if not escolhidas:
        st.error("Escolha pelo menos uma atendente.")
    elif valor <= 0:
        st.error("Informe o valor da meta.")
    else:
        for uid in escolhidas:
            u = disponiveis.loc[uid]
            banco_local.salvar_meta(campanha["id"], uid, u["username"], u["nome"], valor)
        _concluir(f"{len(escolhidas)} adicionada(s).", campanha["id"])

if metas:
    tabela = pd.DataFrame(metas)[["user_id", "nome", "username", "valor_meta"]]
    tabela["remover"] = False
    editada = st.data_editor(
        tabela,
        key=f"editor_metas_{campanha['id']}",
        hide_index=True,
        column_order=["nome", "valor_meta", "remover"],
        disabled=["nome"],
        column_config={
            "nome": st.column_config.TextColumn("Atendente"),
            "valor_meta": st.column_config.NumberColumn(
                "Meta (R$)", min_value=0, step=100, format="localized", required=True
            ),
            "remover": st.column_config.CheckboxColumn("Remover"),
        },
    )
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    salvar = c1.button("Salvar alterações")
    c2.caption(f"Meta total {brl(tabela['valor_meta'].sum())}")
    if salvar:
        for linha in editada.itertuples():
            if linha.remover:
                banco_local.remover_meta(campanha["id"], linha.user_id)
            else:
                banco_local.salvar_meta(
                    campanha["id"], linha.user_id, linha.username, linha.nome, linha.valor_meta
                )
        _concluir("Metas salvas.", campanha["id"])

st.divider()

outras = [c for c in campanhas if c["id"] != campanha["id"]]
if outras:
    with st.expander("Copiar atendentes de outro período"):
        origem = st.selectbox(
            "Copiar de",
            [c["id"] for c in outras],
            format_func=lambda i: rotulo_campanha(por_id[i]),
        )
        if st.button("Copiar"):
            banco_local.copiar_metas(origem, campanha["id"])
            _concluir("Atendentes copiadas.", campanha["id"])

with st.expander("Excluir período"):
    confirmado = st.checkbox(
        "Excluir este período e as metas dele",
        key=f"confirma_exclusao_{campanha['id']}",
    )
    if st.button("Excluir", disabled=not confirmado):
        banco_local.excluir_campanha(campanha["id"])
        _concluir("Período excluído.")
