import base64
import json
from pathlib import Path

import requests


# Troque pela URL publicada no Render.
URL = "https://SEU-SERVICO.onrender.com/nfse/extrair"
API_KEY = "SUA-API-KEY"

PDF = Path(r"C:\CAMINHO\DA\NOTA.pdf")

pdf_base64 = base64.b64encode(PDF.read_bytes()).decode("utf-8")

payload = {
    "base64": pdf_base64,
    "nome_arquivo": PDF.name,
}

resposta = requests.post(
    URL,
    headers={
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    },
    json=payload,
    timeout=120,
)

print("HTTP:", resposta.status_code)
print(json.dumps(resposta.json(), ensure_ascii=False, indent=2))
