"""Conexão com o PostgreSQL usando as credenciais do .env.

A sessão é aberta em modo somente leitura (default_transaction_read_only=on),
então qualquer INSERT/UPDATE/DELETE/DDL feito por engano é rejeitado pelo
próprio servidor, independentemente das permissões do usuário.
"""
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def _host_porta():
    servidor = os.environ["SERVIDOR_DB"]
    host, _, porta = servidor.partition(":")
    return host, int(porta or 5432)


def conectar():
    host, porta = _host_porta()
    return psycopg.connect(
        host=host,
        port=porta,
        user=os.environ["USER_DB"],
        password=os.environ["PASSWORD_DB"],
        dbname=os.environ["BANCO"],
        options="-c default_transaction_read_only=on",
        connect_timeout=10,
        application_name="analise_sgv_vendas",
    )


def consultar(sql, params=None):
    """Executa um SELECT e devolve (colunas, linhas)."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        colunas = [d.name for d in cur.description]
        linhas = cur.fetchall()
        conn.rollback()
    return colunas, linhas


def consultar_df(sql, params=None):
    import pandas as pd

    colunas, linhas = consultar(sql, params)
    return pd.DataFrame(linhas, columns=colunas)
