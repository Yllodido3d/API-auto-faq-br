# 🧠 Respostas Prontas BR

API de respostas automáticas com correspondência de texto em português usando Fuzzy Matching.

## 🚀 Endpoints Principais

| Método | Rota | Descrição |
|--------|------|------------|
| POST | `/responder` | Retorna a resposta mais similar à pergunta enviada |
| GET | `/categorias` | Lista todas as categorias existentes |
| GET | `/perguntas/{cat}` | Lista perguntas de uma categoria |
| POST | `/add` | Adiciona uma nova pergunta/resposta |
| POST | `/importar_csv` | Importa perguntas via arquivo CSV |
| GET | `/status` | Mostra uptime, total de respostas e versão |

## 🔑 Autenticação

Todas as rotas (exceto `/status`) exigem uma **API Key**:
```bash
?api_key=123abc
```

## 💡 Exemplo de Uso
```bash
curl -X POST "https://teu-render-url.onrender.com/responder?api_key=123abc"      -H "Content-Type: application/json"      -d '{"pergunta": "qual seu nome?"}'
```

## 📦 Deploy
O projeto está pronto para deploy no [Render.com](https://render.com) e integração com o [RapidAPI](https://rapidapi.com).
