"""Formatação de valores para exibição (padrão brasileiro)."""


def brl(valor, centavos=True):
    casas = 2 if centavos else 0
    texto = f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def inteiro(valor):
    return f"{int(valor):,}".replace(",", ".")


def data_hora(dt):
    return dt.strftime("%d/%m %H:%M")


def periodo(campanha):
    inicio = data_hora(campanha["inicio"])
    if campanha["fim"] is None:
        return f"desde {inicio}"
    return f"{inicio} até {data_hora(campanha['fim'])}"


_ACENTOS = {"PARA": "Pará", "GOIAS": "Goiás"}


def nome_regiao(nome_empresa):
    nome = (nome_empresa or "").strip().upper()
    return _ACENTOS.get(nome) or nome.title() or "Sem região"


def rotulo_campanha(campanha):
    return f"{campanha['nome']} ({periodo(campanha)})"
