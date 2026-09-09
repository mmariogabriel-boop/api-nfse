# API Extrator NFS-e — Base64

Esta versão **não recebe mais o PDF como `multipart/form-data`**.

O cliente deve converter o PDF para Base64 e enviar o conteúdo em um JSON.

A lógica de mapeamento do `app/extrator.py` foi mantida: a API apenas decodifica o Base64, cria um PDF temporário, executa o extrator e remove o temporário ao final.

## Estrutura

```text
api-nfse/
├── app/
│   ├── __init__.py
│   ├── main.py
│   └── extrator.py
├── .env.example
├── .gitignore
├── cliente_exemplo.py
├── cliente_lote_exemplo.py
├── README.md
└── requirements.txt
```

## Instalação local

```powershell
python -m pip install -r requirements.txt
```

Para executar os exemplos de cliente:

```powershell
python -m pip install requests
```

## Iniciar localmente

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## Variáveis de ambiente

No Render:

```text
API_KEY=SUA-CHAVE
MAX_FILE_MB=20
PYTHON_VERSION=3.13.14
```

O `.env` não deve ser enviado ao GitHub.

## Endpoint — uma NFS-e

```http
POST /nfse/extrair
```

Headers:

```text
X-API-Key: SUA-CHAVE
Content-Type: application/json
```

Body JSON:

```json
{
  "base64": "JVBERi0xLjcK...",
  "nome_arquivo": "NF110.pdf"
}
```

`nome_arquivo` é opcional. Se for omitido, a API usa `documento.pdf`.

O campo `base64` aceita tanto Base64 puro quanto Data URI:

```text
data:application/pdf;base64,JVBERi0xLjcK...
```

### Resposta

```json
{
  "arquivo": "NF110.pdf",
  "numero_nfse": "110",
  "cnpj": "50.270.665/0001-93",
  "razao_social": "EVDL CONSULTORIA E CORRETAGEM LTDA",
  "valor_servico": 1049.24,
  "status": "OK",
  "erro": null
}
```

## Endpoint — lote

```http
POST /nfse/extrair-lote
```

Body:

```json
{
  "arquivos": [
    {
      "base64": "JVBERi0xLjcK...",
      "nome_arquivo": "NF1.pdf"
    },
    {
      "base64": "JVBERi0xLjcK...",
      "nome_arquivo": "NF2.pdf"
    }
  ]
}
```

## Render

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Depois do deploy, a chamada fica, por exemplo:

```text
POST https://SEU-SERVICO.onrender.com/nfse/extrair
```

## Postman

1. Método: `POST`
2. URL: `https://SEU-SERVICO.onrender.com/nfse/extrair`
3. Header `X-API-Key`: sua chave
4. Header `Content-Type`: `application/json`
5. Body -> `raw` -> `JSON`
6. Envie:

```json
{
  "base64": "SEU_BASE64_AQUI",
  "nome_arquivo": "nota.pdf"
}
```

## Observações

- Base64 não é criptografia; a API deve ser usada por HTTPS.
- Base64 aumenta o tamanho do conteúdo em aproximadamente 33%.
- O limite `MAX_FILE_MB` é aplicado ao PDF depois de decodificado.
- A API rejeita conteúdo Base64 que não resulte em um PDF válido.
