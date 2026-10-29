"""Dashboard de metas das atendentes do Live Shop.

Rodar com:  streamlit run app.py
"""
import base64
from pathlib import Path

import streamlit as st

import banco_local

PASTA = Path(__file__).parent


def _estilo():
    # st.html remove <svg>, então o "A" do logo entra como imagem de fundo:
    # branco sobre o azul da faixa, azul sobre o amarelo da comemoração.
    a = (PASTA / "static" / "a.svg").read_text()
    logo = (PASTA / "static" / "logo_negativo.svg").read_text()

    def fundo(svg):
        b64 = base64.b64encode(svg.encode()).decode()
        return f'background-image: url("data:image/svg+xml;base64,{b64}");'

    css = (PASTA / "estilo.css").read_text(encoding="utf-8")
    return (
        f"<style>{css}\n"
        f".hero-a {{ {fundo(a.replace('currentColor', '#ffffff'))} }}\n"
        f".festa-a {{ {fundo(a.replace('currentColor', '#28347c'))} }}\n"
        f".hero-logo {{ {fundo(logo)} }}</style>"
    )


st.set_page_config(page_title="Metas Live Shop", page_icon=str(PASTA / "static" / "logo.svg"), layout="wide")
st.logo(str(PASTA / "static" / "logo.svg"), size="large")
st.html(_estilo())

banco_local.inicializar()

pagina = st.navigation(
    [
        st.Page("paginas/painel.py", title="Painel", icon=":material/monitoring:", default=True),
        st.Page("paginas/configuracao.py", title="Configurar metas", icon=":material/tune:"),
    ]
)
pagina.run()
