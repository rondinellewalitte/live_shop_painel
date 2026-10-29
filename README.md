# Metas Live Shop

Painel de metas das atendentes do Live Shop. Lê os pedidos do PostgreSQL do SGV
(somente leitura) e guarda a configuração das metas num SQLite local (`metas_live.db`).

## Rodar

```
pip install -r requirements.txt
streamlit run app.py
```

## Modo TV

`http://<servidor>:8501/?tv=1` abre o painel numa tela única, sem barra lateral
nem rolagem, ajustado à altura da tela (feito para 1280x720, escala para 1080p).
Usa sempre o período em andamento. Para uma região só: `/?tv=1&regiao=para`
(`tocantins`, `mato grosso`, `matriz`...). Deixe o navegador em tela cheia (F11)
ou abra em modo quiosque: `chrome --kiosk "http://<servidor>:8501/?tv=1"`.

## .env

| Variável | Para quê |
|---|---|
| `SERVIDOR_DB`, `USER_DB`, `PASSWORD_DB`, `BANCO` | Conexão com o PostgreSQL |
| `SENHA_CONFIG` | Senha da tela "Configurar metas". Sem ela, a tela fica aberta |
| `SQLITE_PATH` | Opcional: outro caminho para o banco local |

## Regras de cálculo

- Horários digitados no horário de Brasília (`pedido.data` é UTC no banco).
- Contam os pedidos lançados pela atendente (`pedido.id_usuario`) dentro do período,
  dos tipos escolhidos, exceto os status excluídos (padrão: CANCELADO e ESTORNADO).
- Cliente novo: primeira compra válida do cliente caiu no período; conta para quem
  lançou esse primeiro pedido.
