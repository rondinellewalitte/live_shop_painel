"""Banco local (SQLite) com a configuração das metas.

Guarda só configuração: os períodos de meta (campanhas) e as atendentes
participantes com o valor da meta de cada uma. Os números de venda nunca são
gravados aqui; vêm sempre do PostgreSQL (ver fonte.py), recalculados a cada
atualização, porque status e valor dos pedidos mudam depois de lançados.

Datas de início/fim ficam em texto ISO, no horário de Brasília, sem fuso.
"""
import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

CAMINHO = Path(os.getenv("SQLITE_PATH") or Path(__file__).with_name("metas_live.db"))

TIPOS_PADRAO = ["PRE-VENDA", "EXPRESS", "BRINDE"]
STATUS_EXCLUIDOS_PADRAO = ["CANCELADO", "ESTORNADO"]

_SCHEMA = """
create table if not exists campanhas (
    id               integer primary key autoincrement,
    nome             text not null,
    inicio           text not null,
    fim              text,
    tipos_pedido     text not null,
    status_excluidos text not null,
    criado_em        text not null default (datetime('now', 'localtime'))
);

create table if not exists metas (
    id          integer primary key autoincrement,
    campanha_id integer not null references campanhas(id) on delete cascade,
    user_id     text not null,
    username    text,
    nome        text not null,
    valor_meta  real not null check (valor_meta >= 0),
    unique (campanha_id, user_id)
);
"""


@contextmanager
def _conexao():
    # Uma conexão por chamada: o Streamlit reexecuta o script em threads diferentes.
    with closing(sqlite3.connect(CAMINHO)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        with conn:
            yield conn


def inicializar():
    with _conexao() as conn:
        conn.executescript(_SCHEMA)


def _campanha(linha):
    if linha is None:
        return None
    c = dict(linha)
    c["inicio"] = datetime.fromisoformat(c["inicio"])
    c["fim"] = datetime.fromisoformat(c["fim"]) if c["fim"] else None
    c["tipos_pedido"] = json.loads(c["tipos_pedido"])
    c["status_excluidos"] = json.loads(c["status_excluidos"])
    return c


def listar_campanhas():
    with _conexao() as conn:
        linhas = conn.execute("select * from campanhas order by inicio desc, id desc").fetchall()
    return [_campanha(l) for l in linhas]


def obter_campanha(campanha_id):
    with _conexao() as conn:
        linha = conn.execute("select * from campanhas where id = ?", (campanha_id,)).fetchone()
    return _campanha(linha)


def salvar_campanha(nome, inicio, fim, tipos_pedido, status_excluidos, campanha_id=None):
    """Cria (campanha_id=None) ou atualiza um período de meta. Devolve o id."""
    valores = (
        nome.strip(),
        inicio.isoformat(timespec="minutes"),
        fim.isoformat(timespec="minutes") if fim else None,
        json.dumps(list(tipos_pedido)),
        json.dumps(list(status_excluidos)),
    )
    with _conexao() as conn:
        if campanha_id is None:
            cur = conn.execute(
                "insert into campanhas (nome, inicio, fim, tipos_pedido, status_excluidos)"
                " values (?, ?, ?, ?, ?)",
                valores,
            )
            return cur.lastrowid
        conn.execute(
            "update campanhas set nome = ?, inicio = ?, fim = ?, tipos_pedido = ?,"
            " status_excluidos = ? where id = ?",
            (*valores, campanha_id),
        )
        return campanha_id


def excluir_campanha(campanha_id):
    with _conexao() as conn:
        conn.execute("delete from campanhas where id = ?", (campanha_id,))


def campanha_atual(campanhas, agora):
    """A campanha em andamento agora; senão a de início mais recente."""
    for c in campanhas:
        if c["inicio"] <= agora and (c["fim"] is None or agora < c["fim"]):
            return c
    return campanhas[0] if campanhas else None


def listar_metas(campanha_id):
    with _conexao() as conn:
        linhas = conn.execute(
            "select * from metas where campanha_id = ? order by nome", (campanha_id,)
        ).fetchall()
    return [dict(l) for l in linhas]


def salvar_meta(campanha_id, user_id, username, nome, valor_meta):
    """Inclui a atendente na campanha ou atualiza o valor da meta dela."""
    with _conexao() as conn:
        conn.execute(
            "insert into metas (campanha_id, user_id, username, nome, valor_meta)"
            " values (?, ?, ?, ?, ?)"
            " on conflict (campanha_id, user_id) do update set"
            " username = excluded.username, nome = excluded.nome,"
            " valor_meta = excluded.valor_meta",
            (campanha_id, user_id, username, nome.strip(), float(valor_meta)),
        )


def remover_meta(campanha_id, user_id):
    with _conexao() as conn:
        conn.execute(
            "delete from metas where campanha_id = ? and user_id = ?", (campanha_id, user_id)
        )


def copiar_metas(origem_id, destino_id):
    """Copia atendentes e valores de outra campanha (sobrescreve quem já estiver)."""
    for m in listar_metas(origem_id):
        salvar_meta(destino_id, m["user_id"], m["username"], m["nome"], m["valor_meta"])
