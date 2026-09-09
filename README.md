# API Extrator NFS-e

A API recebe PDFs de NFS-e e retorna:

- Número da NFS-e
- CNPJ do prestador
- Razão Social
- Valor do serviço
- Status

## Instalação

Dentro da pasta do projeto:

```bash
py -m pip install -r requirements.txt
```

Para executar os exemplos de cliente:

```bash
py -m pip install requests
```

## Iniciar

No Windows, execute:

```text
iniciar_api.bat
```

ou:

```bash
py -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Abra:

```text
http://127.0.0.1:8000/docs
```

## API Key de teste

O `.env` está configurado inicialmente com:

```text
chave-teste-nfse-2026
```

Use no header:

```text
X-API-Key: chave-teste-nfse-2026
```

Troque a chave antes de publicar a API.

## Uma nota

```text
POST /nfse/extrair
```

Campo multipart:

```text
arquivo
```

## Várias notas

```text
POST /nfse/extrair-lote
```

Campo multipart repetido:

```text
arquivos
```

## Produção

Antes de publicar:

- troque a API Key;
- remova `--reload`;
- utilize HTTPS;
- não envie o `.env` para Git;
- defina limites de upload adequados.
