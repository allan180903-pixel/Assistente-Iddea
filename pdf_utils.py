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
