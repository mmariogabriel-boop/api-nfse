import os
import secrets
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
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

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
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
    version="1.0.0",
    description=(
        "Recebe documentos PDF de NFS-e, extrai número da nota, "
        "CNPJ do prestador, razão social e valor do serviço."
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

    if not chave_recebida or not secrets.compare_digest(
        chave_recebida,
        API_KEY,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida ou não informada.",
        )


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

async def salvar_pdf_temporario(arquivo: UploadFile) -> Path:
    """
    Salva o upload em arquivo temporário sem carregar o PDF inteiro na memória.
    Também valida assinatura PDF e tamanho máximo.
    """
    nome = arquivo.filename or "documento.pdf"

    if not nome.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"O arquivo '{nome}' não possui extensão .pdf.",
        )

    caminho_temp = None
    tamanho = 0
    primeiro_bloco = True

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".pdf",
            delete=False,
        ) as temp:
            caminho_temp = Path(temp.name)

            while True:
                bloco = await arquivo.read(1024 * 1024)

                if not bloco:
                    break

                if primeiro_bloco:
                    primeiro_bloco = False

                    if not bloco.startswith(b"%PDF"):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"O arquivo '{nome}' não parece ser um PDF válido.",
                        )

                tamanho += len(bloco)

                if tamanho > MAX_FILE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            f"O arquivo '{nome}' ultrapassa o limite "
                            f"de {MAX_FILE_MB} MB."
                        ),
                    )

                temp.write(bloco)

        if tamanho == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"O arquivo '{nome}' está vazio.",
            )

        return caminho_temp

    except Exception:
        if caminho_temp and caminho_temp.exists():
            caminho_temp.unlink(missing_ok=True)
        raise

    finally:
        await arquivo.close()


async def processar_arquivo(arquivo: UploadFile) -> NFSeResponse:
    nome_arquivo = arquivo.filename or "documento.pdf"
    caminho_temp = None

    try:
        caminho_temp = await salvar_pdf_temporario(arquivo)

        dados = await run_in_threadpool(
            extrair_dados_nfse,
            caminho_temp,
        )

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
        "versao": "1.0.0",
        "status": "online",
        "documentacao": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
    }


@app.post(
    "/nfse/extrair",
    response_model=NFSeResponse,
    dependencies=[Depends(validar_api_key)],
)
async def extrair_nfse(
    arquivo: UploadFile = File(...),
):
    resultado = await processar_arquivo(arquivo)

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
async def extrair_nfse_lote(
    arquivos: list[UploadFile] = File(...),
):
    if not arquivos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum arquivo foi enviado.",
        )

    resultados: list[NFSeResponse] = []

    for arquivo in arquivos:
        try:
            resultado = await processar_arquivo(arquivo)
        except HTTPException as erro:
            resultado = NFSeResponse(
                arquivo=arquivo.filename or "documento.pdf",
                status="ERRO",
                erro=str(erro.detail),
            )

        resultados.append(resultado)

    sucessos = sum(
        1 for item in resultados
        if item.status == "OK"
    )

    revisar = sum(
        1 for item in resultados
        if item.status.startswith("REVISAR")
    )

    erros = sum(
        1 for item in resultados
        if item.status == "ERRO"
    )

    return LoteResponse(
        quantidade=len(resultados),
        processados_com_sucesso=sucessos,
        revisar=revisar,
        erros=erros,
        notas=resultados,
    )
