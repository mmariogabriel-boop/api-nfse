import base64
import json
from pathlib import Path

import requests


URL = "https://SEU-SERVICO.onrender.com/nfse/extrair-lote"
API_KEY = "SUA-API-KEY"
PASTA = Path(r"C:\CAMINHO\DAS\NOTAS")

arquivos = []

for pdf in PASTA.glob("*.pdf"):
    arquivos.append(
        {
            "base64": base64.b64encode(pdf.read_bytes()).decode("utf-8"),
            "nome_arquivo": pdf.name,
        }
    )

resposta = requests.post(
    URL,
    headers={
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    },
    json={"arquivos": arquivos},
    timeout=300,
)

print("HTTP:", resposta.status_code)
print(json.dumps(resposta.json(), ensure_ascii=False, indent=2))
