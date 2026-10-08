# API NFS-e Base64 com OCR automático

A API continua recebendo o PDF em Base64.

## Fluxo de leitura

### Caminho 1 — PDF com texto

```text
Base64
  ↓
PDF temporário
  ↓
pdfplumber
  ↓
texto encontrado
  ↓
regex + leitura por posição
  ↓
JSON
```

### Caminho 2 — PDF imagem / escaneado

```text
Base64
  ↓
PDF temporário
  ↓
pdfplumber
  ↓
sem texto
  ↓
PyMuPDF renderiza a página
  ↓
RapidOCR
  ↓
mapeamento dos campos
  ↓
JSON
```

Também existe recuperação automática: se o PDF tiver texto,
mas algum dos quatro campos não for encontrado, o OCR tenta
preencher apenas os campos faltantes.

## Campos retornados

- Número da NFS-e
- CNPJ do prestador
- Razão Social do prestador
- Valor do Serviço
- Status

## Endpoint

`POST /nfse/extrair`

Headers:

```text
X-API-Key: SUA_CHAVE
Content-Type: application/json
```

Body:

```json
{
  "base64": "JVBERi0xLjcK...",
  "nome_arquivo": "nota.pdf"
}
```

## Render

Build:

```text
pip install -r requirements.txt
```

Start:

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Variáveis:

```text
API_KEY=SUA_CHAVE
MAX_FILE_MB=20
PYTHON_VERSION=3.13.14
```

Não é necessário instalar Tesseract no Render.
O OCR principal usa RapidOCR + ONNXRuntime.
