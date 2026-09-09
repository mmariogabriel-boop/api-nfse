from pathlib import Path
import re
import pdfplumber

# ============================================================
# EXTRAÇÃO DOS DADOS DA NFS-e
# Modelos: DANFSe v1.0/v2.0 + DANFESe v2.0 + NFSe municipais (ex.: Santa Teresa/ES e Vila Velha/ES)
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
    return match.group(0) if match else None


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


def extrair_dados_nfse(caminho_pdf: Path) -> dict:
    texto = extrair_texto_pdf(caminho_pdf)

    if not texto.strip():
        raise ValueError("PDF sem texto pesquisável. Pode ser um PDF escaneado/imagem.")

    # --------------------------------------------------------
    # NÚMERO DA NFS-e
    # --------------------------------------------------------
    numero_nfse = extrair_numero_nfse(texto)

    # --------------------------------------------------------
    # PRESTADOR / FORNECEDOR
    # --------------------------------------------------------
    cnpj = extrair_cnpj_prestador(texto)
    razao_social = extrair_razao_social_por_layout(caminho_pdf)
    if not razao_social:
        razao_social = extrair_razao_social_texto(texto)

    # --------------------------------------------------------
    # VALOR DO SERVIÇO
    # --------------------------------------------------------
    valor_servico_texto = extrair_valor_servico(texto, caminho_pdf)
    valor_servico = valor_brl_para_float(valor_servico_texto)

    # Campos faltantes para facilitar conferência
    faltando = []
    if not numero_nfse:
        faltando.append("NÚMERO NFS-e")
    if not cnpj:
        faltando.append("CNPJ")
    if not razao_social:
        faltando.append("RAZÃO SOCIAL")
    if valor_servico is None:
        faltando.append("VALOR DO SERVIÇO")

    status = "OK" if not faltando else "REVISAR: " + ", ".join(faltando)

    return {
        "NÚMERO DA NFS-e": numero_nfse,
        "CNPJ": cnpj,
        "RAZÃO SOCIAL": razao_social,
        "VALOR DO SERVIÇO": valor_servico,
        "STATUS": status,
    }


