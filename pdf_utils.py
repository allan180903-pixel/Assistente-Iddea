import io
from fpdf import FPDF
from datetime import datetime


def gerar_boleto_pdf(conta: dict) -> bytes:
    boleto = conta.get("boleto", {})
    valor = conta.get("valor_documento", 0)
    vencimento = conta.get("data_vencimento", "")
    emissao = conta.get("data_emissao", "")
    num_nf = conta.get("numero_documento_fiscal", "")
    num_parcela = conta.get("numero_parcela", "")
    num_pedido = conta.get("numero_pedido", "")
    cod_barras = conta.get("codigo_barras_ficha_compensacao", "")
    num_boleto = boleto.get("cNumBancario", "")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # Cabeçalho
    pdf.set_fill_color(26, 58, 92)
    pdf.rect(0, 0, 210, 18, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(15, 5)
    pdf.cell(0, 8, "FORMMA COMPONENTES LTDA", ln=True)
    pdf.set_text_color(0, 0, 0)

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "BOLETO BANCÁRIO", ln=True, align="C")
    pdf.ln(4)

    # Dados principais
    def linha(label, valor_txt):
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(240, 244, 248)
        pdf.cell(55, 7, label, border=1, fill=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 7, str(valor_txt), border=1, ln=True)

    linha("Número do Boleto:", num_boleto)
    linha("NF / Pedido:", f"NF {num_nf}  |  Pedido {num_pedido}  |  Parcela {num_parcela}")
    linha("Data de Emissão:", emissao)
    linha("Data de Vencimento:", vencimento)
    linha("Valor (R$):", f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    pdf.ln(8)

    # Código de barras (texto)
    if cod_barras:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 7, "Linha Digitável:", ln=True)
        pdf.set_font("Courier", "", 10)
        pdf.set_fill_color(248, 248, 248)
        pdf.multi_cell(0, 7, cod_barras, border=1, fill=True, align="C")

    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f"Documento gerado em {datetime.today().strftime('%d/%m/%Y %H:%M')} - Formma Componentes", ln=True, align="C")

    return pdf.output()


def gerar_proposta_pdf(empresa: str, cliente_nome: str, itens: list,
                        condicao_pagamento: str = "", observacao: str = "",
                        numero_pedido: str = "") -> bytes:
    """Gera PDF de proposta comercial estilo IDDEA."""
    BROWN = (61, 41, 30)
    TAUPE = (196, 184, 176)
    CREAM = (245, 240, 236)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # ── Cabeçalho ────────────────────────────────────────────────────────────
    pdf.set_fill_color(*TAUPE)
    pdf.rect(0, 0, 210, 30, "F")
    pdf.set_text_color(*BROWN)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_xy(15, 7)
    pdf.cell(90, 10, empresa.upper(), ln=False)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(110, 8)
    pdf.cell(0, 5, "PROPOSTA COMERCIAL", ln=True)
    if numero_pedido:
        pdf.set_xy(110, 14)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, f"Pedido OMIE: {numero_pedido}")

    pdf.set_text_color(0, 0, 0)
    pdf.ln(20)

    # ── Info cliente ──────────────────────────────────────────────────────────
    pdf.set_fill_color(*CREAM)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(30, 7, "Cliente:", fill=True, border=0)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 7, cliente_nome, ln=True, fill=True)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(30, 7, "Data:", fill=True, border=0)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 7, datetime.today().strftime("%d/%m/%Y"), ln=True, fill=True)

    if condicao_pagamento:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(30, 7, "Pagamento:", fill=True, border=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 7, condicao_pagamento, ln=True, fill=True)

    pdf.ln(6)

    # ── Tabela de itens ───────────────────────────────────────────────────────
    # Header
    pdf.set_fill_color(*BROWN)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(10, 7, "#", border=0, fill=True, align="C")
    pdf.cell(85, 7, "PRODUTO", border=0, fill=True)
    pdf.cell(15, 7, "UN", border=0, fill=True, align="C")
    pdf.cell(20, 7, "QTD", border=0, fill=True, align="R")
    pdf.cell(25, 7, "VL UNIT (R$)", border=0, fill=True, align="R")
    pdf.cell(15, 7, "DESC%", border=0, fill=True, align="R")
    pdf.cell(25, 7, "TOTAL (R$)", border=0, fill=True, align="R")
    pdf.ln()

    # Itens
    pdf.set_text_color(0, 0, 0)
    total_geral = 0
    for i, item in enumerate(itens, 1):
        fill_color = CREAM if i % 2 == 0 else (255, 255, 255)
        pdf.set_fill_color(*fill_color)
        pdf.set_font("Helvetica", "", 8)

        qty = item.get("quantidade", 0)
        vunit = item.get("valor_unitario", 0)
        desc_pct = item.get("desconto", 0)
        total_item = qty * vunit * (1 - desc_pct / 100)
        total_geral += total_item

        def fmt(v): return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        pdf.cell(10, 6, str(i), fill=True, align="C")
        pdf.cell(85, 6, item.get("descricao", "")[:45], fill=True)
        pdf.cell(15, 6, item.get("unidade", "UN"), fill=True, align="C")
        pdf.cell(20, 6, fmt(qty), fill=True, align="R")
        pdf.cell(25, 6, fmt(vunit), fill=True, align="R")
        pdf.cell(15, 6, f"{desc_pct:.1f}%", fill=True, align="R")
        pdf.cell(25, 6, fmt(total_item), fill=True, align="R")
        pdf.ln()

    # Total
    pdf.ln(2)
    pdf.set_fill_color(*TAUPE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(155, 8, "TOTAL GERAL", fill=True, align="R")
    pdf.cell(25, 8, f"R$ {fmt(total_geral)}", fill=True, align="R")
    pdf.ln()

    # Observação
    if observacao:
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 6, "Observações:", ln=True)
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(0, 5, observacao)

    # Rodapé
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, f"Documento gerado em {datetime.today().strftime('%d/%m/%Y %H:%M')} — {empresa}", align="C")

    return pdf.output()


def gerar_relatorio_pdf(titulo: str, linhas: list[dict], colunas: list[str]) -> bytes:
    pdf = FPDF()
    pdf.add_page("L")  # landscape para tabelas largas
    pdf.set_margins(10, 10, 10)

    # Cabeçalho
    pdf.set_fill_color(26, 58, 92)
    pdf.rect(0, 0, 297, 16, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_xy(10, 4)
    pdf.cell(0, 8, f"FORMMA COMPONENTES — {titulo.upper()}", ln=True)
    pdf.set_text_color(0, 0, 0)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, f"Gerado em {datetime.today().strftime('%d/%m/%Y %H:%M')}", ln=True)
    pdf.ln(3)

    if not linhas:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 8, "Nenhum registro encontrado.", ln=True)
        return pdf.output()

    largura_pagina = 277  # A4 landscape útil
    col_w = largura_pagina // len(colunas)

    # Header tabela
    pdf.set_fill_color(52, 100, 160)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    for col in colunas:
        pdf.cell(col_w, 7, col, border=1, fill=True)
    pdf.ln()

    # Linhas
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 8)
    for i, linha in enumerate(linhas):
        fill = i % 2 == 0
        pdf.set_fill_color(245, 248, 252) if fill else pdf.set_fill_color(255, 255, 255)
        for col in colunas:
            val = str(linha.get(col, ""))[:30]
            pdf.cell(col_w, 6, val, border=1, fill=True)
        pdf.ln()

    return pdf.output()
