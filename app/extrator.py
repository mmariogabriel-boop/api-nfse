from pathlib import Path
import re
import pdfplumber

# ============================================================
# EXTRAÇÃO DOS DADOS DA NFS-e
# Modelos: DANFSe v1.0/v2.0 + DANFESe v2.0 (inclusive CNPJ sem pontuação) + NFSe municipais (ex.: Santa Teresa/ES e Vila Velha/ES)
# ============================================================

def limpar_texto(texto: str) -> str:
    """Remove espaços repetidos e quebras desnecessárias."""
    texto = texto.replace("\r", "\n")
    texto = re.sub(r"[ \t]+", " ", texto)
    return texto.strip()


def valor_brl_para_float(valor: str):
    """Converte '21.478,17' em 21478.17 para o Excel tratar como número."""
    if not valor:
        return None
    try:
        return float(valor.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def extrair_texto_pdf(caminho_pdf: Path) -> str:
    """
    Extrai o texto do PDF preservando melhor as colunas do DANFSe.

    Alguns PDFs do mesmo modelo visual possuem uma estrutura interna diferente:
    - em alguns, os campos aparecem um abaixo do outro;
    - em outros, os campos da mesma linha ficam lado a lado.

    use_text_flow=False é mais estável para os dois formatos.
    """
    partes = []

    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text(
                use_text_flow=False,
                x_tolerance=1,
                y_tolerance=3,
            )
            if texto:
                partes.append(texto)

    return "\n".join(partes)


def procurar_regex(padrao: str, texto: str, flags=0):
    resultado = re.search(padrao, texto, flags)
    return resultado.group(1).strip() if resultado else None


def extrair_numero_nfse(texto: str):
    """Extrai o número da NFS-e nos modelos suportados."""
    padroes = [
        # DANFSe Nacional: cabeçalho em colunas.
        r"N[ÚU]MERO\s+DA\s+NFS-e[^\n]*\n\s*(\d+)\b",

        # DANFSe Nacional: formato mais linear.
        r"N[ÚU]MERO\s+DA\s+NFS-e\s*\n\s*(\d+)\b",

        # Rodapé DANFSe Nacional: N° NFS-e / CHAVE NFS-e -> 147 / chave...
        r"N[°º]\s*NFS-e\s*/\s*CHAVE\s*NFS-e[^\n]*\n\s*(\d+)\s*/",

        # NFSe municipal (ex.: Vila Velha/Nibo): "Número da nota".
        r"N[ÚU]mero\s+da\s+nota[^\n]*\n\s*(\d+)\b",
    ]

    for padrao in padroes:
        valor = procurar_regex(padrao, texto, re.IGNORECASE)
        if valor:
            return valor

    # NFSe municipal (ex.: Santa Teresa/ES):
    # "... Nº da Nota Fiscal" pode aparecer no fim de uma linha e o número
    # uma ou duas linhas abaixo, pois os campos do cabeçalho são extraídos por colunas.
    linhas = [linha.strip() for linha in texto.splitlines()]
    for i, linha in enumerate(linhas):
        if re.search(r"N[º°o]?\s*da\s*Nota\s*Fiscal", linha, re.IGNORECASE):
            for proxima in linhas[i + 1:i + 4]:
                m = re.fullmatch(r"\s*(\d{1,12})\s*", proxima)
                if m:
                    return m.group(1)

    # Fallback para PDFs cujo texto interno venha praticamente sem espaços.
    compacto = re.sub(r"\s+", "", texto)
    match = re.search(r"N[ÚU]MERODANFS-e.*?(\d+)", compacto, re.IGNORECASE)
    if match:
        return match.group(1)

    match = re.search(r"N[º°o]?daNotaFiscal.*?(\d{1,12})", compacto, re.IGNORECASE)
    return match.group(1) if match else None


def extrair_secao_prestador(texto: str):
    """
    Retorna somente o bloco do prestador/emitente.

    Suporta:
    - DANFSe/DANFESe Nacional: PRESTADOR / FORNECEDOR ...
    - DANFSe v1.0: EMITENTE DA NFS-e ... TOMADOR DO SERVIÇO
    - NFSe municipal: PRESTADOR ... TOMADOR
    """
    padroes = [
        # Portal Nacional v2.0 / DANFESe v2.0
        r"PRESTADOR\s*/\s*FORNECEDOR(.*?)(?=TOMADOR\s*/?\s*ADQUIRENTE|DESTINAT[ÁA]RIO|INTERMEDI[ÁA]RIO|SERVI[CÇ]O\s+PRESTADO)",

        # DANFSe v1.0 - Vitória: emitente é o prestador
        r"EMITENTE\s+DA\s+NFS[-–]?e(.*?)(?=TOMADOR\s+DO\s+SERVI[CÇ]O)",

        # NFSe municipal (ex.: Vila Velha/Nibo)
        r"(?:^|\n)\s*PRESTADOR\s+DE\s+SERVI[CÇ]OS\s*(.*?)(?=(?:^|\n)\s*TOMADOR\s+DE\s+SERVI[CÇ]OS)",

        # NFSe municipal (ex.: Santa Teresa)
        r"(?:^|\n)\s*PRESTADOR\s*(.*?)(?=(?:^|\n)\s*TOMADOR\s*(?:\n|$))",
    ]

    for padrao in padroes:
        match = re.search(
            padrao,
            texto,
            re.IGNORECASE | re.DOTALL | re.MULTILINE,
        )
        if match:
            return match.group(1)

    return None


def extrair_cnpj_prestador(texto: str):
    """Pega o CNPJ somente do prestador/emitente, nunca do tomador."""
    secao = extrair_secao_prestador(texto)
    if not secao:
        return None

    # Modelos municipais: "CPF/CNPJ: ..." ou "CNPJ/CPF: ..."
    match = re.search(
        r"(?:CPF\s*/\s*CNPJ|CNPJ\s*/\s*CPF)\s*:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})",
        secao,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)

    # Modelos nacionais: primeiro CNPJ formatado dentro do bloco do prestador.
    match = re.search(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", secao)
    if match:
        return match.group(0)

    # Alguns DANFESe v2.0 trazem o CNPJ sem pontuação, por exemplo:
    # 39277397000107
    # Como a busca está limitada ao bloco do PRESTADOR, evitamos capturar
    # o CNPJ do tomador/adquirente.
    match = re.search(r"(?<!\d)(\d{14})(?!\d)", secao)
    if match:
        cnpj = match.group(1)

        # Padroniza o retorno para XX.XXX.XXX/XXXX-XX.
        return (
            f"{cnpj[0:2]}.{cnpj[2:5]}.{cnpj[5:8]}/"
            f"{cnpj[8:12]}-{cnpj[12:14]}"
        )

    return None


def extrair_razao_social_por_layout(caminho_pdf: Path):
    """
    Extrai a Razão Social pela posição dos textos no PDF.

    A estratégia funciona nos DANFSe/DANFESe nacionais porque a razão social
    fica na primeira coluna e Município/E-mail começam em uma coluna à direita.
    Também cobre o DANFSe v1.0, em que não existe o título PRESTADOR / FORNECEDOR:
    nesse caso usamos a seção EMITENTE DA NFS-e como início do bloco.
    """
    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            palavras = pagina.extract_words(
                use_text_flow=False,
                keep_blank_chars=False,
                x_tolerance=1,
                y_tolerance=3,
            )

            if not palavras:
                continue

            # Início do bloco do prestador.
            prestadores = [
                p for p in palavras
                if p["text"].upper() == "PRESTADOR"
            ]
            emitentes = [
                p for p in palavras
                if p["text"].upper().startswith("EMITENTE")
            ]

            # Início do tomador. Aceita TOMADOR, TOMADOR/ADQUIRENTE e TOMADOR DO SERVIÇO.
            tomadores = [
                p for p in palavras
                if p["text"].upper().startswith("TOMADOR")
            ]

            if not tomadores:
                continue

            top_tomador = min(p["top"] for p in tomadores)

            candidatos_inicio = [
                p["top"] for p in prestadores
                if p["top"] < top_tomador
            ]

            if candidatos_inicio:
                # Preferimos o PRESTADOR mais próximo do tomador, evitando palavras
                # "Prestador" que possam aparecer no cabeçalho como valor de campo.
                top_inicio = max(candidatos_inicio)
            else:
                candidatos_emitente = [
                    p["top"] for p in emitentes
                    if p["top"] < top_tomador
                ]
                if not candidatos_emitente:
                    continue
                top_inicio = max(candidatos_emitente)

            # Cabeçalho "Nome / Nome Empresarial" dentro do prestador/emitente.
            nomes_header = [
                p for p in palavras
                if p["text"].lower() == "nome"
                and p["x0"] < 160
                and top_inicio < p["top"] < top_tomador
            ]

            if not nomes_header:
                continue

            top_nome = min(p["top"] for p in nomes_header)
            x_nome = min(p["x0"] for p in nomes_header if abs(p["top"] - top_nome) <= 1.5)

            # O fim do nome empresarial é o próximo cabeçalho "Endereço" da 1ª coluna.
            enderecos = [
                p for p in palavras
                if p["text"].lower().startswith("endere")
                and p["x0"] < 160
                and top_nome < p["top"] < top_tomador
            ]

            if not enderecos:
                continue

            top_endereco = min(p["top"] for p in enderecos)

            # Descobre dinamicamente onde começa a segunda coluna na mesma linha
            # do cabeçalho Nome / Nome Empresarial (Município, E-mail etc.).
            palavras_linha_nome = [
                p for p in palavras
                if abs(p["top"] - top_nome) <= 1.5
                and p["x0"] > x_nome + 100
            ]

            if palavras_linha_nome:
                x_limite = min(p["x0"] for p in palavras_linha_nome) - 5
            else:
                # Fallback adequado aos layouts A4 nacionais atuais.
                x_limite = pagina.width * 0.50

            palavras_razao = [
                p for p in palavras
                if (top_nome + 2) < p["top"] < (top_endereco - 1)
                and p["x0"] < x_limite
            ]

            if palavras_razao:
                palavras_razao.sort(key=lambda p: (round(p["top"], 1), p["x0"]))
                razao = " ".join(p["text"] for p in palavras_razao)
                razao = limpar_texto(razao)

                # Evita devolver textos de rótulo por engano.
                if razao and not re.match(r"^(Munic[ií]pio|E-?mail|Endere[cç]o)\b", razao, re.IGNORECASE):
                    return razao

    return None


def extrair_razao_social_texto(texto: str):
    """Fallback textual para modelos municipais e variações lineares."""
    secao = extrair_secao_prestador(texto)
    if not secao:
        return None

    # Modelo municipal: Razão Social: EMPRESA...
    match = re.search(r"Raz[aã]o\s+Social\s*:\s*([^\n]+)", secao, re.IGNORECASE)
    if match:
        return limpar_texto(match.group(1))

    # NFSe municipal (ex.: Vila Velha/Nibo): Nome/Razão Social: EMPRESA...
    match = re.search(
        r"Nome\s*/\s*Raz[aã]o\s+Social\s*:\s*([^\n]+)",
        secao,
        re.IGNORECASE,
    )
    if match:
        return limpar_texto(match.group(1))

    # Modelo nacional linear: pega a linha após Nome / Nome Empresarial.
    # Em alguns PDFs a linha também contém município/e-mail; nesses casos o
    # extrator por layout deve ter prioridade e este bloco é apenas fallback.
    match = re.search(
        r"Nome\s*/\s*Nome\s+Empresarial[^\n]*\n\s*([^\n]+)",
        secao,
        re.IGNORECASE,
    )
    if match:
        linha = limpar_texto(match.group(1))
        # Remove e-mail ao fim, quando estiver na mesma linha.
        linha = re.sub(r"\s+\S+@\S+\s*$", "", linha).strip()
        return linha or None

    return None


def normalizar_token(texto: str) -> str:
    """Normaliza token para comparação de rótulos, preservando / e R$."""
    import unicodedata
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.upper().strip()


def extrair_valor_operacao_por_layout(caminho_pdf: Path):
    """
    Extrai o valor posicionado abaixo de "VALOR DA OPERAÇÃO / SERVIÇO".

    É importante usar coordenadas aqui: no DANFESe de Cariacica o mesmo bloco
    possui VALOR TOTAL e VALOR DA OPERAÇÃO na mesma linha. Uma regex simples
    pode pegar o valor da coluna errada.
    """
    alvo = ["VALOR", "DA", "OPERACAO", "/", "SERVICO"]

    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            palavras = pagina.extract_words(
                use_text_flow=False,
                keep_blank_chars=False,
                x_tolerance=1,
                y_tolerance=3,
            )
            if not palavras:
                continue

            # Agrupa palavras que pertencem visualmente à mesma linha.
            linhas = []
            for p in sorted(palavras, key=lambda w: (round(w["top"], 1), w["x0"])):
                encontrada = None
                for linha in linhas:
                    if abs(linha["top"] - p["top"]) <= 1.5:
                        encontrada = linha
                        break
                if encontrada is None:
                    encontrada = {"top": p["top"], "words": []}
                    linhas.append(encontrada)
                encontrada["words"].append(p)

            for linha in linhas:
                ws = sorted(linha["words"], key=lambda w: w["x0"])
                tokens = [normalizar_token(w["text"]) for w in ws]

                # Procura a sequência VALOR DA OPERAÇÃO / SERVIÇO dentro da linha.
                indice = None
                for i in range(0, len(tokens) - len(alvo) + 1):
                    if tokens[i:i + len(alvo)] == alvo:
                        indice = i
                        break

                if indice is None:
                    continue

                x_inicio = ws[indice]["x0"]
                fim_indice = indice + len(alvo) - 1
                x_fim_rotulo = ws[fim_indice]["x1"]

                # Próxima coluna da mesma linha, se houver.
                proximos = [w["x0"] for w in ws[fim_indice + 1:] if w["x0"] > x_fim_rotulo + 8]
                x_fim = min(proximos) - 3 if proximos else pagina.width

                # Valores normalmente aparecem de 5 a 18 pontos abaixo do rótulo.
                candidatos = [
                    w for w in palavras
                    if linha["top"] + 2 < w["top"] < linha["top"] + 22
                    and x_inicio - 3 <= w["x0"] < x_fim
                ]

                if candidatos:
                    candidatos.sort(key=lambda w: (w["top"], w["x0"]))
                    texto_valor = " ".join(w["text"] for w in candidatos)
                    match = re.search(r"R\$\s*([\d.]+,\d{2})", texto_valor, re.IGNORECASE)
                    if match:
                        return match.group(1)

    return None


def extrair_valor_servico(texto: str, caminho_pdf: Path | None = None):
    """Extrai o valor bruto do serviço/operação nos modelos suportados."""

    # Para DANFSe/DANFESe com colunas, posição é mais segura que regex.
    if caminho_pdf is not None:
        valor_layout = extrair_valor_operacao_por_layout(caminho_pdf)
        if valor_layout:
            return valor_layout

    padroes = [
        # DANFSe v1.0: "Valor do Serviço ..." e o valor fica na linha seguinte.
        r"Valor\s+do\s+Servi[cç]o[^\n]*\n\s*R\$\s*([\d.]+,\d{2})",

        # DANFSe Nacional: quando o campo estiver linearizado corretamente.
        r"VALOR\s+DA\s+OPERA[CÇ][AÃ]O\s*/\s*SERVI[CÇ]O[^\n]*\n\s*R\$\s*([\d.]+,\d{2})",

        # NFSe municipal (Santa Teresa/ES): tabela VALOR SERVIÇO (R$).
        r"VALOR\s+SERVI[CÇ]O\s*\(R\$\)[^\n]*\n\s*([\d.]+,\d{2})\b",

        # NFSe municipal (Vila Velha/Nibo): "VALOR TOTAL DA NOTA R$ 1.049,24".
        r"VALOR\s+TOTAL\s+DA\s+NOTA\s+R\$\s*([\d.]+,\d{2})\b",
    ]

    for padrao in padroes:
        valor = procurar_regex(padrao, texto, re.IGNORECASE | re.DOTALL)
        if valor:
            return valor

    # Fallback municipal: discriminação contendo "Valor 3.488,37".
    secao_discriminacao = re.search(
        r"DISCRIMINA[CÇ][AÃ]O\s+DOS\s+SERVI[CÇ]OS(.*?)(?:VALOR\s+SERVI[CÇ]O|DEMONSTRATIVO)",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    if secao_discriminacao:
        match = re.search(
            r"(?:^|\n)\s*Valor\s+([\d.]+,\d{2})\b",
            secao_discriminacao.group(1),
            re.IGNORECASE,
        )
        if match:
            return match.group(1)

    # Últimos fallbacks para PDFs com texto interno praticamente sem espaços.
    compacto = re.sub(r"\s+", "", texto)

    match = re.search(
        r"ValordoServi[cç]o.*?R\$([\d.]+,\d{2})",
        compacto,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)

    match = re.search(r"VALORSERVI[CÇ]O\(R\$\).*?([\d.]+,\d{2})", compacto, re.IGNORECASE)
    return match.group(1) if match else None



# ============================================================
# OCR - CAMINHO 2 PARA PDF ESCANEADO / IMAGEM
# ============================================================

_RAPID_OCR_ENGINE = None


def _normalizar_ocr(texto: str) -> str:
    """Normaliza texto para comparação de rótulos vindos do OCR."""
    import unicodedata

    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )
    texto = texto.upper()
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _formatar_cnpj(cnpj: str):
    """Aceita CNPJ formatado ou 14 dígitos e devolve XX.XXX.XXX/XXXX-XX."""
    if not cnpj:
        return None

    digitos = re.sub(r"\D", "", cnpj)

    if len(digitos) != 14:
        return None

    return (
        f"{digitos[0:2]}.{digitos[2:5]}.{digitos[5:8]}/"
        f"{digitos[8:12]}-{digitos[12:14]}"
    )


def _executar_ocr_rapidocr(caminho_pdf: Path):
    """
    OCR principal para produção/Render.

    O RapidOCR roda via Python/ONNXRuntime e não depende do executável
    externo do Tesseract. O PDF é renderizado em imagem pelo PyMuPDF.
    """
    global _RAPID_OCR_ENGINE

    import fitz
    import numpy as np
    from io import BytesIO
    from PIL import Image
    from rapidocr import RapidOCR

    if _RAPID_OCR_ENGINE is None:
        _RAPID_OCR_ENGINE = RapidOCR()

    itens = []

    documento = fitz.open(caminho_pdf)

    try:
        for numero_pagina, pagina in enumerate(documento):

            # ~216 DPI. Boa relação entre leitura e consumo de memória.
            matriz = fitz.Matrix(3.0, 3.0)

            pix = pagina.get_pixmap(
                matrix=matriz,
                alpha=False,
            )

            imagem = Image.open(
                BytesIO(
                    pix.tobytes("png")
                )
            ).convert("RGB")

            imagem_np = np.array(imagem)

            resultado = _RAPID_OCR_ENGINE(imagem_np)

            if resultado is None:
                continue

            textos = getattr(resultado, "txts", None)
            caixas = getattr(resultado, "boxes", None)
            scores = getattr(resultado, "scores", None)

            if textos is None:
                continue

            for indice, texto_item in enumerate(textos):

                texto_item = limpar_texto(str(texto_item))

                if not texto_item:
                    continue

                score = 1.0

                if scores is not None and indice < len(scores):
                    try:
                        score = float(scores[indice])
                    except Exception:
                        score = 1.0

                # Descarta apenas reconhecimentos muito ruins.
                if score < 0.30:
                    continue

                x0 = 0.0
                y0 = float(indice)
                x1 = float(imagem.width)
                y1 = y0 + 1.0

                if caixas is not None and indice < len(caixas):
                    try:
                        pontos = np.asarray(caixas[indice], dtype=float)

                        x0 = float(pontos[:, 0].min())
                        x1 = float(pontos[:, 0].max())
                        y0 = float(pontos[:, 1].min())
                        y1 = float(pontos[:, 1].max())
                    except Exception:
                        pass

                itens.append({
                    "pagina": numero_pagina,
                    "texto": texto_item,
                    "score": score,
                    "x0": x0,
                    "x1": x1,
                    "y0": y0,
                    "y1": y1,
                    "largura_pagina": float(imagem.width),
                })

    finally:
        documento.close()

    itens.sort(
        key=lambda item: (
            item["pagina"],
            round(item["y0"], 1),
            item["x0"],
        )
    )

    texto = "\n".join(
        item["texto"]
        for item in itens
    )

    return texto, itens


def _executar_ocr_tesseract_fallback(caminho_pdf: Path):
    """
    Fallback opcional para desenvolvimento local.

    Só é usado se RapidOCR não estiver disponível e se o computador
    tiver pytesseract + executável Tesseract instalados.
    """
    import fitz
    import pytesseract
    from io import BytesIO
    from PIL import Image
    from pytesseract import Output

    itens = []
    documento = fitz.open(caminho_pdf)

    try:
        for numero_pagina, pagina in enumerate(documento):

            pix = pagina.get_pixmap(
                matrix=fitz.Matrix(3.0, 3.0),
                alpha=False,
            )

            imagem = Image.open(
                BytesIO(
                    pix.tobytes("png")
                )
            ).convert("RGB")

            dados = pytesseract.image_to_data(
                imagem,
                lang="eng",
                config="--psm 6",
                output_type=Output.DICT,
            )

            grupos = {}

            total = len(dados["text"])

            for i in range(total):
                palavra = limpar_texto(dados["text"][i])

                if not palavra:
                    continue

                try:
                    confianca = float(dados["conf"][i])
                except Exception:
                    confianca = -1

                if confianca < 20:
                    continue

                chave = (
                    dados["block_num"][i],
                    dados["par_num"][i],
                    dados["line_num"][i],
                )

                grupos.setdefault(chave, []).append({
                    "texto": palavra,
                    "x0": float(dados["left"][i]),
                    "y0": float(dados["top"][i]),
                    "x1": float(dados["left"][i] + dados["width"][i]),
                    "y1": float(dados["top"][i] + dados["height"][i]),
                    "score": confianca / 100.0,
                })

            for palavras in grupos.values():

                palavras.sort(
                    key=lambda item: item["x0"]
                )

                texto_linha = " ".join(
                    item["texto"]
                    for item in palavras
                )

                itens.append({
                    "pagina": numero_pagina,
                    "texto": texto_linha,
                    "score": sum(
                        item["score"]
                        for item in palavras
                    ) / len(palavras),
                    "x0": min(item["x0"] for item in palavras),
                    "x1": max(item["x1"] for item in palavras),
                    "y0": min(item["y0"] for item in palavras),
                    "y1": max(item["y1"] for item in palavras),
                    "largura_pagina": float(imagem.width),
                })

    finally:
        documento.close()

    itens.sort(
        key=lambda item: (
            item["pagina"],
            round(item["y0"], 1),
            item["x0"],
        )
    )

    texto = "\n".join(
        item["texto"]
        for item in itens
    )

    return texto, itens


def extrair_texto_com_ocr(caminho_pdf: Path):
    """
    Caminho OCR.

    1. Tenta RapidOCR, usado no Render.
    2. Se não estiver disponível, tenta Tesseract local.
    """
    erros = []

    try:
        texto, itens = _executar_ocr_rapidocr(caminho_pdf)

        if texto.strip():
            return texto, itens

        erros.append("RapidOCR não encontrou texto.")

    except Exception as erro:
        erros.append(
            f"RapidOCR: {erro}"
        )

    try:
        texto, itens = _executar_ocr_tesseract_fallback(caminho_pdf)

        if texto.strip():
            return texto, itens

        erros.append("Tesseract não encontrou texto.")

    except Exception as erro:
        erros.append(
            f"Tesseract: {erro}"
        )

    raise ValueError(
        "Não foi possível extrair texto do PDF nem aplicar OCR. "
        + " | ".join(erros)
    )


def _secao_ocr_prestador(itens):
    """Recorta visualmente os itens entre PRESTADOR e TOMADOR."""
    inicio = None
    fim = None

    for indice, item in enumerate(itens):
        normalizado = _normalizar_ocr(item["texto"])

        if inicio is None:
            if (
                "PRESTADOR" in normalizado
                and (
                    "FORNECEDOR" in normalizado
                    or "SERVICOS" in normalizado
                    or normalizado == "PRESTADOR"
                )
            ):
                inicio = indice
                continue

        elif "TOMADOR" in normalizado:
            fim = indice
            break

    if inicio is None:
        return itens

    if fim is None:
        return itens[inicio + 1:]

    return itens[inicio + 1:fim]


def extrair_numero_nfse_ocr(texto: str, itens):
    """Extrai o número da NFS-e a partir do texto/posição do OCR."""

    numero = extrair_numero_nfse(texto)

    if numero:
        return numero

    # Busca visualmente o rótulo "NÚMERO DA NFS-e".
    for item in itens:
        normalizado = _normalizar_ocr(item["texto"])

        if (
            "NUMERO" in normalizado
            and "NFS" in normalizado
            and "DPS" not in normalizado
        ):
            candidatos = [
                candidato
                for candidato in itens
                if candidato["pagina"] == item["pagina"]
                and item["y1"] <= candidato["y0"] <= item["y1"] + 160
                and candidato["x0"] <= item["x1"] + 120
                and candidato["x1"] >= item["x0"] - 40
            ]

            candidatos.sort(
                key=lambda candidato: (
                    candidato["y0"],
                    abs(candidato["x0"] - item["x0"]),
                )
            )

            for candidato in candidatos:
                match = re.search(
                    r"(?<!\d)(\d{1,12})(?!\d)",
                    candidato["texto"],
                )

                if match:
                    return match.group(1)

    # Fallback para linhas OCR como:
    # "19 05/10/2026 05/10/2026..."
    linhas = [
        limpar_texto(linha)
        for linha in texto.splitlines()
        if limpar_texto(linha)
    ]

    for i, linha in enumerate(linhas):
        normalizado = _normalizar_ocr(linha)

        if (
            "NUMERO" in normalizado
            and "NFS" in normalizado
            and "DPS" not in normalizado
        ):
            for proxima in linhas[i + 1:i + 8]:
                match = re.match(
                    r"^\s*(\d{1,12})(?:\s|$)",
                    proxima,
                )

                if match:
                    return match.group(1)

    return None


def extrair_cnpj_prestador_ocr(texto: str, itens):
    """Extrai o CNPJ do prestador no caminho OCR."""

    cnpj = extrair_cnpj_prestador(texto)

    if cnpj:
        return cnpj

    secao = _secao_ocr_prestador(itens)

    for item in secao:
        match = re.search(
            r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b",
            item["texto"],
        )

        if match:
            return match.group(0)

        match = re.search(
            r"(?<!\d)(\d{14})(?!\d)",
            item["texto"],
        )

        if match:
            return _formatar_cnpj(
                match.group(1)
            )

    return None


def _limpar_razao_ocr(razao: str):
    """Remove município/UF/CEP que eventualmente venham na mesma linha."""
    if not razao:
        return None

    razao = limpar_texto(razao)

    # Ex.:
    # MR CONSULTORIA E SERVICOS LTDA Vitoria / ES 32.05309 / 29.015-360
    #
    # O município normalmente vem em caixa mista (Vitoria, Vila Velha etc.),
    # enquanto a razão social costuma vir em caixa alta.
    match = re.search(
        r"\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-zà-ÿ]+"
        r"(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]?[a-zà-ÿ]+)*"
        r"\s*/\s*[A-Z]{2}"
        r"(?:\s+\d[\d.\-/ ]+)?\s*$",
        razao,
    )

    if match:
        razao = razao[:match.start()].strip()

    # Remove eventuais rótulos de coluna ao final.
    razao = re.split(
        r"\s+(?:Munic[ií]pio|C[oó]digo\s+IBGE|CEP|E-?mail)\b",
        razao,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()

    return razao or None


def extrair_razao_social_ocr(texto: str, itens):
    """Extrai a razão social do prestador no caminho OCR."""

    secao = _secao_ocr_prestador(itens)

    # Primeiro tenta pela posição visual.
    for indice, item in enumerate(secao):
        normalizado = _normalizar_ocr(item["texto"])

        if (
            "NOME" in normalizado
            and "EMPRESARIAL" in normalizado
        ):
            largura = item.get(
                "largura_pagina",
                1000.0,
            )

            candidatos = []

            for candidato in secao[indice + 1:indice + 12]:

                if candidato["pagina"] != item["pagina"]:
                    continue

                if candidato["y0"] <= item["y0"] + 2:
                    continue

                if candidato["y0"] > item["y0"] + 220:
                    break

                # Razão social deve estar na primeira metade da página.
                if candidato["x0"] > largura * 0.56:
                    continue

                texto_candidato = limpar_texto(
                    candidato["texto"]
                )

                normalizado_candidato = _normalizar_ocr(
                    texto_candidato
                )

                if not texto_candidato:
                    continue

                if re.search(
                    r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}",
                    texto_candidato,
                ):
                    continue

                if re.fullmatch(
                    r"\d{14}",
                    re.sub(r"\D", "", texto_candidato),
                ):
                    continue

                rotulos = (
                    "ENDERECO",
                    "MUNICIPIO",
                    "EMAIL",
                    "TELEFONE",
                    "CODIGO IBGE",
                    "INDICADOR MUNICIPAL",
                    "SIMPLES NACIONAL",
                    "REGIME",
                    "CNPJ",
                    "CPF",
                )

                if any(
                    normalizado_candidato.startswith(rotulo)
                    for rotulo in rotulos
                ):
                    continue

                if len(texto_candidato) >= 4:
                    candidatos.append(candidato)

            if candidatos:
                candidatos.sort(
                    key=lambda candidato: (
                        candidato["y0"],
                        candidato["x0"],
                    )
                )

                razao = _limpar_razao_ocr(
                    candidatos[0]["texto"]
                )

                if razao:
                    return razao

    # Depois tenta o mesmo parser textual já usado nos PDFs normais.
    razao = extrair_razao_social_texto(texto)

    return _limpar_razao_ocr(razao)


def _parece_rotulo_valor_operacao(texto: str):
    normalizado = _normalizar_ocr(texto)

    # Alguns OCRs confundem C/Ç com G:
    # OPERACAO -> OPERAGAO
    # SERVICO  -> SERVIGO
    tem_valor = "VALOR" in normalizado
    tem_operacao = (
        "OPERACAO" in normalizado
        or "OPERAGAO" in normalizado
    )
    tem_servico = (
        "SERVICO" in normalizado
        or "SERVIGO" in normalizado
    )

    return tem_valor and tem_operacao and tem_servico


def extrair_valor_servico_ocr(texto: str, itens):
    """Extrai o valor da operação/serviço no caminho OCR."""

    # Primeiro tenta as regras textuais existentes.
    valor = extrair_valor_servico(
        texto,
        caminho_pdf=None,
    )

    if valor:
        return valor

    # Depois tenta pela posição do rótulo no OCR.
    for item in itens:

        if not _parece_rotulo_valor_operacao(
            item["texto"]
        ):
            continue

        centro_x = (
            item["x0"] + item["x1"]
        ) / 2

        largura_rotulo = max(
            item["x1"] - item["x0"],
            80.0,
        )

        candidatos = []

        for candidato in itens:

            if candidato["pagina"] != item["pagina"]:
                continue

            if candidato["y0"] < item["y0"] + 2:
                continue

            if candidato["y0"] > item["y0"] + 180:
                continue

            match = re.search(
                r"R?\$?\s*([\d.]+,\d{2})",
                candidato["texto"],
                re.IGNORECASE,
            )

            if not match:
                continue

            centro_candidato = (
                candidato["x0"] + candidato["x1"]
            ) / 2

            distancia_x = abs(
                centro_candidato - centro_x
            )

            # Prioriza valores abaixo da mesma coluna.
            if distancia_x <= largura_rotulo * 0.80 + 100:
                candidatos.append(
                    (
                        candidato["y0"],
                        distancia_x,
                        match.group(1),
                    )
                )

        if candidatos:
            candidatos.sort(
                key=lambda valor_item: (
                    valor_item[0],
                    valor_item[1],
                )
            )

            return candidatos[0][2]

    # ----------------------------------------------------
    # Fallback do quadro "VALOR TOTAL DA NFS-e".
    #
    # Alguns mecanismos de OCR perdem especificamente o texto
    # "VALOR DA OPERAÇÃO / SERVIÇO" por causa das linhas da tabela.
    # No DANFSe, o valor da operação aparece imediatamente abaixo
    # desse cabeçalho, dentro do mesmo quadro final.
    # ----------------------------------------------------
    linhas = [
        limpar_texto(linha)
        for linha in texto.splitlines()
        if limpar_texto(linha)
    ]

    for indice, linha in enumerate(linhas):
        normalizado = _normalizar_ocr(linha)

        if "VALOR TOTAL" not in normalizado:
            continue

        # Evita capturar blocos tributários como "Valor Total Apurado".
        if "APURADO" in normalizado:
            continue

        trecho = linhas[indice + 1:indice + 4]

        # Confirma que estamos no quadro final procurando também
        # a linha de valor líquido/retenções logo abaixo.
        contexto = " ".join(
            linhas[indice:indice + 6]
        )
        contexto_normalizado = _normalizar_ocr(
            contexto
        )

        if (
            "VALOR LIQUIDO" not in contexto_normalizado
            and "RETEN" not in contexto_normalizado
        ):
            continue

        for proxima in trecho:
            match = re.search(
                r"R\$\s*([\d.]+,\d{2})",
                proxima,
                re.IGNORECASE,
            )

            if match:
                return match.group(1)

    # Fallback textual tolerante aos erros mais comuns do OCR.
    import unicodedata

    sem_acentos = unicodedata.normalize(
        "NFKD",
        texto,
    )

    sem_acentos = "".join(
        caractere
        for caractere in sem_acentos
        if not unicodedata.combining(caractere)
    ).upper()

    compacto = re.sub(
        r"\s+",
        "",
        sem_acentos,
    )

    padroes = [
        r"VALORDAOPERA(?:C|G)AO.{0,8}SERVI(?:C|G)O.{0,350}?R\$\s*([\d.]+,\d{2})",
        r"VALORTOTALDANFS.{0,350}?R\$\s*([\d.]+,\d{2})",
    ]

    for padrao in padroes:
        match = re.search(
            padrao,
            compacto,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    return None


def _montar_retorno(
    numero_nfse,
    cnpj,
    razao_social,
    valor_servico_texto,
):
    valor_servico = valor_brl_para_float(
        valor_servico_texto
    )

    faltando = []

    if not numero_nfse:
        faltando.append(
            "NÚMERO NFS-e"
        )

    if not cnpj:
        faltando.append(
            "CNPJ"
        )

    if not razao_social:
        faltando.append(
            "RAZÃO SOCIAL"
        )

    if valor_servico is None:
        faltando.append(
            "VALOR DO SERVIÇO"
        )

    status_extracao = (
        "OK"
        if not faltando
        else "REVISAR: " + ", ".join(faltando)
    )

    return {
        "NÚMERO DA NFS-e": numero_nfse,
        "CNPJ": cnpj,
        "RAZÃO SOCIAL": razao_social,
        "VALOR DO SERVIÇO": valor_servico,
        "STATUS": status_extracao,
    }


def extrair_dados_nfse(caminho_pdf: Path) -> dict:
    """
    Fluxo automático:

    CAMINHO 1
    PDF com texto pesquisável
        -> pdfplumber
        -> regex/layout existentes

    CAMINHO 2
    PDF escaneado / apenas imagem
        -> OCR
        -> regras específicas de OCR

    RECUPERAÇÃO
    Se o PDF tiver texto, mas algum campo ficar faltando,
    o OCR é usado apenas como segunda tentativa para preencher
    os campos ausentes.
    """

    caminho_pdf = Path(caminho_pdf)

    texto = extrair_texto_pdf(
        caminho_pdf
    )

    # ========================================================
    # CAMINHO 1 - PDF COM TEXTO
    # ========================================================

    if texto.strip():

        numero_nfse = extrair_numero_nfse(
            texto
        )

        cnpj = extrair_cnpj_prestador(
            texto
        )

        razao_social = extrair_razao_social_por_layout(
            caminho_pdf
        )

        if not razao_social:
            razao_social = extrair_razao_social_texto(
                texto
            )

        valor_servico_texto = extrair_valor_servico(
            texto,
            caminho_pdf,
        )

        resultado = _montar_retorno(
            numero_nfse,
            cnpj,
            razao_social,
            valor_servico_texto,
        )

        # Tudo encontrado: não gastamos processamento com OCR.
        if resultado["STATUS"] == "OK":
            return resultado

        # ----------------------------------------------------
        # RECUPERAÇÃO:
        # existe texto, mas algum campo não foi localizado.
        # O OCR tenta preencher somente o que faltou.
        # ----------------------------------------------------

        try:
            texto_ocr, itens_ocr = extrair_texto_com_ocr(
                caminho_pdf
            )

            if not numero_nfse:
                numero_nfse = extrair_numero_nfse_ocr(
                    texto_ocr,
                    itens_ocr,
                )

            if not cnpj:
                cnpj = extrair_cnpj_prestador_ocr(
                    texto_ocr,
                    itens_ocr,
                )

            if not razao_social:
                razao_social = extrair_razao_social_ocr(
                    texto_ocr,
                    itens_ocr,
                )

            if not valor_servico_texto:
                valor_servico_texto = extrair_valor_servico_ocr(
                    texto_ocr,
                    itens_ocr,
                )

            return _montar_retorno(
                numero_nfse,
                cnpj,
                razao_social,
                valor_servico_texto,
            )

        except Exception:
            # Se o OCR falhar, devolve o resultado do caminho normal
            # em vez de derrubar a nota inteira.
            return resultado

    # ========================================================
    # CAMINHO 2 - PDF SEM TEXTO / ESCANEADO / IMAGEM
    # ========================================================

    texto_ocr, itens_ocr = extrair_texto_com_ocr(
        caminho_pdf
    )

    numero_nfse = extrair_numero_nfse_ocr(
        texto_ocr,
        itens_ocr,
    )

    cnpj = extrair_cnpj_prestador_ocr(
        texto_ocr,
        itens_ocr,
    )

    razao_social = extrair_razao_social_ocr(
        texto_ocr,
        itens_ocr,
    )

    valor_servico_texto = extrair_valor_servico_ocr(
        texto_ocr,
        itens_ocr,
    )

    return _montar_retorno(
        numero_nfse,
        cnpj,
        razao_social,
        valor_servico_texto,
    )
