"""Consultas ao PostgreSQL do SGV (somente leitura, via conexao.py).

Atenção ao fuso: pedido.data é gravado em UTC, sem fuso. Os horários da
campanha são digitados no horário de Brasília e convertidos para UTC antes de
irem para a consulta. A coluna não é convertida no SQL, para o índice
idx_pedido_data continuar sendo usado.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from conexao import consultar_df

FUSO = ZoneInfo("America/Sao_Paulo")

TIPOS_ATENDIMENTO = ("PRE-VENDA", "EXPRESS")


def agora_local():
    return datetime.now(FUSO).replace(tzinfo=None)


def para_utc(dt_local):
    """Horário de Brasília (sem fuso) -> UTC sem fuso, como pedido.data é gravado."""
    return dt_local.replace(tzinfo=FUSO).astimezone(timezone.utc).replace(tzinfo=None)


def _utc_para_local(serie):
    return pd.to_datetime(serie).dt.tz_localize("UTC").dt.tz_convert(FUSO).dt.tz_localize(None)


def _filtro(ini_utc, fim_utc, user_ids, tipos, excluidos):
    condicoes = [
        "p.data >= %(ini)s",
        "p.id_usuario = any(%(users)s::uuid[])",
        "p.tipo_pedido = any(%(tipos)s)",
        "coalesce(p.status, '') <> all(%(excl)s)",
    ]
    params = {
        "ini": ini_utc,
        "users": list(user_ids),
        "tipos": list(tipos),
        "excl": list(excluidos),
    }
    if fim_utc is not None:
        condicoes.append("p.data < %(fim)s")
        params["fim"] = fim_utc
    return " and ".join(condicoes), params


def _numeros(df, colunas):
    for c in colunas:
        df[c] = pd.to_numeric(df[c]).astype(float)
    return df


def resumo_por_atendente(ini_utc, fim_utc, user_ids, tipos, excluidos):
    where, params = _filtro(ini_utc, fim_utc, user_ids, tipos, excluidos)
    df = consultar_df(
        f"""
        select p.id_usuario::text as user_id,
               count(*) as pedidos,
               coalesce(sum(p.valor_total), 0) as faturamento,
               count(distinct p.id_cliente) as clientes
        from pedido p
        where {where}
        group by 1
        """,
        params,
    )
    return _numeros(df, ["pedidos", "faturamento", "clientes"])


def clientes_novos(ini_utc, fim_utc, user_ids, tipos, excluidos):
    """Clientes cuja primeira compra válida (de qualquer tipo) caiu no período.

    Se mais de uma atendente atendeu o mesmo cliente novo, conta para quem
    lançou o primeiro pedido.
    """
    where, params = _filtro(ini_utc, fim_utc, user_ids, tipos, excluidos)
    df = consultar_df(
        f"""
        with primeira as (
            select distinct on (p.id_cliente) p.id_cliente, p.id_usuario
            from pedido p
            where {where} and p.id_cliente is not null
            order by p.id_cliente, p.data
        )
        select pr.id_usuario::text as user_id, count(*) as novos
        from primeira pr
        where not exists (
            select 1 from pedido a
            where a.id_cliente = pr.id_cliente
              and a.data < %(ini)s
              and coalesce(a.status, '') <> all(%(excl)s)
        )
        group by 1
        """,
        params,
    )
    return _numeros(df, ["novos"])


def por_hora(ini_utc, fim_utc, user_ids, tipos, excluidos):
    """Pedidos e faturamento por hora (horário de Brasília), somando as participantes."""
    where, params = _filtro(ini_utc, fim_utc, user_ids, tipos, excluidos)
    df = consultar_df(
        f"""
        select date_trunc('hour', p.data) as hora,
               count(*) as pedidos,
               coalesce(sum(p.valor_total), 0) as faturamento
        from pedido p
        where {where}
        group by 1
        order by 1
        """,
        params,
    )
    df["hora"] = _utc_para_local(df["hora"])
    return _numeros(df, ["pedidos", "faturamento"])


def ultimos_pedidos(ini_utc, fim_utc, user_ids, tipos, excluidos, limite=8):
    where, params = _filtro(ini_utc, fim_utc, user_ids, tipos, excluidos)
    params["limite"] = limite
    df = consultar_df(
        f"""
        select p.id, p.data, p.id_usuario::text as user_id, p.tipo_pedido, p.valor_total
        from pedido p
        where {where}
        order by p.data desc
        limit %(limite)s
        """,
        params,
    )
    df["data"] = _utc_para_local(df["data"])
    return _numeros(df, ["valor_total"])


def regioes_atendentes(user_ids, desde_utc):
    """Região (empresa) de cada atendente: pedido.id_vendedor -> vendedor -> empresa.

    Vale a empresa da maioria dos pedidos dela desde `desde_utc`; hoje cada
    atendente vende para uma empresa só, isto só desempata exceções.
    """
    return consultar_df(
        """
        select distinct on (p.id_usuario)
               p.id_usuario::text as user_id, e.id_empresa, e.nome_empresa
        from pedido p
        join vendedor v on v.id_vendedor = p.id_vendedor
        join empresa e on e.id_empresa = v.id_empresa
        where p.data >= %(desde)s
          and p.id_usuario = any(%(users)s::uuid[])
        group by p.id_usuario, e.id_empresa, e.nome_empresa
        order by p.id_usuario, count(*) desc, e.id_empresa
        """,
        {"desde": desde_utc, "users": list(user_ids)},
    )


def dados_painel(ini_utc, fim_utc, user_ids, tipos, excluidos):
    args = (ini_utc, fim_utc, user_ids, tipos, excluidos)
    return {
        "resumo": resumo_por_atendente(*args),
        "novos": clientes_novos(*args),
        "por_hora": por_hora(*args),
        "ultimos": ultimos_pedidos(*args),
    }


def usuarios(dias=60, somente_atendentes=True):
    """Usuários ativos para cadastrar na meta (a coluna password nunca é lida).

    Com somente_atendentes, só quem lançou PRE-VENDA/EXPRESS nos últimos `dias`.
    """
    desde = para_utc(agora_local() - timedelta(days=dias))
    juncao = "join" if somente_atendentes else "left join"
    df = consultar_df(
        f"""
        select u.id::text as user_id, u.username, trim(u.name) as nome,
               count(p.id) as pedidos
        from users u
        {juncao} pedido p on p.id_usuario = u.id
                         and p.data >= %(desde)s
                         and p.tipo_pedido = any(%(tipos)s)
        where u.enabled
        group by 1, 2, 3
        order by pedidos desc, nome
        """,
        {"desde": desde, "tipos": list(TIPOS_ATENDIMENTO)},
    )
    df["nome"] = df["nome"].fillna(df["username"])
    return _numeros(df, ["pedidos"])


def opcoes_pedido():
    """Tipos e status de pedido existentes no banco, para as listas da configuração."""
    tipos = consultar_df("select distinct tipo_pedido as v from pedido where tipo_pedido is not null order by 1")
    status = consultar_df("select distinct status as v from pedido where status is not null order by 1")
    return tipos["v"].tolist(), status["v"].tolist()
