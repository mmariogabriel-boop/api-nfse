import base64
import binascii
import os
import re
import secrets
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from .extrator import extrair_dados_nfse


# ============================================================
# CONFIGURAÇÕES
# ============================================================

load_dotenv()

API_KEY = os.getenv("API_KEY", "").strip()
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "20"))
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

# Um PDF codificado em Base64 fica aproximadamente 33% maior.
MAX_BASE64_CHARS = ((MAX_FILE_BYTES + 2) // 3) * 4 + 4096

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
)


# ============================================================
# MODELOS DE ENTRADA
# ============================================================

class NFSeBase64Request(BaseModel):
    """Payload esperado para uma NFS-e."""

    base64: str = Field(
        ...,
        min_length=10,
        description=(
            "PDF codificado em Base64. Aceita Base64 puro ou "
            "Data URI: data:application/pdf;base64,..."
        ),
    )
    nome_arquivo: str = Field(
        default="documento.pdf",
        description="Nome opcional do arquivo, usado apenas no retorno/log.",
    )


class LoteBase64Request(BaseModel):
    arquivos: list[NFSeBase64Request] = Field(
        ...,
        min_length=1,
        description="Lista de documentos em Base64.",
    )


# ============================================================
# MODELOS DE RESPOSTA
# ============================================================

class NFSeResponse(BaseModel):
    arquivo: str
    numero_nfse: str | None = None
    cnpj: str | None = None
    razao_social: str | None = None
    valor_servico: float | None = None
    status: str
    erro: str | None = None


class LoteResponse(BaseModel):
    quantidade: int
    processados_com_sucesso: int
    revisar: int
    erros: int
    notas: list[NFSeResponse] = Field(default_factory=list)


# ============================================================
# API
# ============================================================

app = FastAPI(
    title="API Extrator NFS-e",
    version="2.0.0",
    description=(
        "Recebe o PDF da NFS-e em Base64 dentro de um JSON, "
        "decodifica temporariamente, executa o mapeamento e retorna "
        "número da NFS-e, CNPJ do prestador, razão social e valor do serviço."
    ),
)


# ============================================================
# SEGURANÇA
# ============================================================

def validar_api_key(chave_recebida: str | None = Depends(api_key_header)):
    if not API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API_KEY não configurada no servidor.",
        )

    if not chave_recebida or not secrets.compare_digest(chave_recebida, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida ou não informada.",
        )


# ============================================================
# BASE64 / PDF
# ============================================================

def normalizar_base64(valor: str) -> str:
    """Normaliza Base64 puro ou Data URI e corrige padding ausente."""
    if not valor or not valor.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O campo 'base64' está vazio.",
        )

    valor = valor.strip()

    # Suporta: data:application/pdf;base64,JVBERi0x...
    if valor.lower().startswith("data:"):
        cabecalho, separador, conteudo = valor.partition(",")
        if not separador or ";base64" not in cabecalho.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Data URI Base64 inválida.",
            )
        valor = conteudo

    # Remove espaços/quebras de linha inseridos por alguns sistemas.
    valor = re.sub(r"\s+", "", valor)

    if len(valor) > MAX_BASE64_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"O Base64 excede o limite configurado para PDFs "
                f"de até {MAX_FILE_MB} MB."
            ),
        )

    # Base64 pode chegar sem '=' no fim.
    resto = len(valor) % 4
    if resto:
        valor += "=" * (4 - resto)

    return valor


def decodificar_pdf_base64(valor: str, nome_arquivo: str) -> bytes:
    base64_normalizado = normalizar_base64(valor)

    try:
        pdf_bytes = base64.b64decode(base64_normalizado, validate=True)
    except (binascii.Error, ValueError) as erro:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Base64 inválido para '{nome_arquivo}'.",
        ) from erro

    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"O documento '{nome_arquivo}' está vazio.",
        )

    if len(pdf_bytes) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"O PDF '{nome_arquivo}' ultrapassa o limite "
                f"de {MAX_FILE_MB} MB."
            ),
        )

    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"O Base64 de '{nome_arquivo}' foi decodificado, "
                "mas o conteúdo não é um PDF válido."
            ),
        )

    return pdf_bytes


def salvar_pdf_temporario(pdf_bytes: bytes) -> Path:
    """Cria apenas um PDF temporário para o pdfplumber processar."""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".pdf", delete=False) as temp:
        temp.write(pdf_bytes)
        return Path(temp.name)


# ============================================================
# PROCESSAMENTO
# ============================================================

async def processar_documento(requisicao: NFSeBase64Request) -> NFSeResponse:
    nome_arquivo = (requisicao.nome_arquivo or "documento.pdf").strip()
    if not nome_arquivo:
        nome_arquivo = "documento.pdf"
    if not nome_arquivo.lower().endswith(".pdf"):
        nome_arquivo += ".pdf"

    caminho_temp: Path | None = None

    try:
        pdf_bytes = decodificar_pdf_base64(requisicao.base64, nome_arquivo)
        caminho_temp = salvar_pdf_temporario(pdf_bytes)

        # O extrator é síncrono; tiramos o processamento do event loop da API.
        dados = await run_in_threadpool(extrair_dados_nfse, caminho_temp)

        return NFSeResponse(
            arquivo=nome_arquivo,
            numero_nfse=dados.get("NÚMERO DA NFS-e"),
            cnpj=dados.get("CNPJ"),
            razao_social=dados.get("RAZÃO SOCIAL"),
            valor_servico=dados.get("VALOR DO SERVIÇO"),
            status=dados.get("STATUS", "REVISAR"),
        )

    except HTTPException:
        raise

    except Exception as erro:
        return NFSeResponse(
            arquivo=nome_arquivo,
            status="ERRO",
            erro=str(erro),
        )

    finally:
        if caminho_temp and caminho_temp.exists():
            caminho_temp.unlink(missing_ok=True)


# ============================================================
# ENDPOINTS
# ============================================================

@app.get("/")
def raiz():
    return {
        "api": "API Extrator NFS-e",
        "versao": "2.0.0",
        "entrada": "JSON com PDF em Base64",
        "status": "online",
        "documentacao": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "versao": "2.0.0",
        "entrada": "base64",
    }


@app.post(
    "/nfse/extrair",
    response_model=NFSeResponse,
    dependencies=[Depends(validar_api_key)],
)
async def extrair_nfse(requisicao: NFSeBase64Request):
    """
    Recebe uma NFS-e em JSON.

    Exemplo:

    ```json
    {
      "base64": "JVBERi0xLjcK...",
      "nome_arquivo": "NF110.pdf"
    }
    ```
    """
    resultado = await processar_documento(requisicao)

    if resultado.status == "ERRO":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "arquivo": resultado.arquivo,
                "erro": resultado.erro,
            },
        )

    return resultado


@app.post(
    "/nfse/extrair-lote",
    response_model=LoteResponse,
    dependencies=[Depends(validar_api_key)],
)
async def extrair_nfse_lote(requisicao: LoteBase64Request):
    """Recebe várias NFS-e em Base64 na mesma requisição."""
    resultados: list[NFSeResponse] = []

    for arquivo in requisicao.arquivos:
        try:
            resultado = await processar_documento(arquivo)
        except HTTPException as erro:
            resultado = NFSeResponse(
                arquivo=arquivo.nome_arquivo or "documento.pdf",
                status="ERRO",
                erro=str(erro.detail),
            )
        resultados.append(resultado)

    sucessos = sum(1 for item in resultados if item.status == "OK")
    revisar = sum(1 for item in resultados if item.status.startswith("REVISAR"))
    erros = sum(1 for item in resultados if item.status == "ERRO")

    return LoteResponse(
        quantidade=len(resultados),
        processados_com_sucesso=sucessos,
        revisar=revisar,
        erros=erros,
        notas=resultados,
    )
