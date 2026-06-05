import streamlit as st
import anthropic
import json
import base64
import time
from datetime import datetime, date, timedelta
from omie_api import (
    EMPRESAS, get_api,
    consolidar_contas_receber, consolidar_contas_pagar,
    consolidar_pedidos, consolidar_resumo, consolidar_estoque,
)
from pdf_utils import gerar_boleto_pdf, gerar_relatorio_pdf, gerar_proposta_pdf

import os
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

TOOLS = [
    {
        "name": "listar_contas_receber",
        "description": "Lista contas a receber do OMIE.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dias_vencimento": {"type": "integer", "default": 30},
                "status": {"type": "string", "description": "EMABERTO, ATRASADO, AVENCER, VENCEHOJE, PAGO, LIQUIDADO. Vazio para todos.", "default": "EMABERTO"}
            }
        }
    },
    {
        "name": "listar_contas_pagar",
        "description": "Lista contas a pagar do OMIE.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dias_vencimento": {"type": "integer", "default": 30},
                "status": {"type": "string", "description": "EMABERTO, ATRASADO, AVENCER, VENCEHOJE, PAGO, LIQUIDADO. Vazio para todos.", "default": "EMABERTO"}
            }
        }
    },
    {
        "name": "listar_pedidos_venda",
        "description": "Lista pedidos de venda do OMIE.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dias": {"type": "integer", "default": 30},
                "status": {"type": "string", "default": ""}
            }
        }
    },
    {
        "name": "listar_notas_fiscais",
        "description": "Lista notas fiscais emitidas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dias": {"type": "integer", "default": 60}
            }
        }
    },
    {
        "name": "buscar_boleto_por_nf",
        "description": "Busca dados do boleto de uma NF específica.",
        "input_schema": {
            "type": "object",
            "properties": {"numero_nf": {"type": "string"}},
            "required": ["numero_nf"]
        }
    },
    {
        "name": "consultar_cliente",
        "description": "Busca cliente pelo nome.",
        "input_schema": {
            "type": "object",
            "properties": {"nome_cliente": {"type": "string"}},
            "required": ["nome_cliente"]
        }
    },
    {
        "name": "resumo_financeiro",
        "description": "Resumo geral financeiro: contas a receber, atrasadas e a pagar.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "consultar_estoque",
        "description": "Consulta estoque de produtos. Use para responder perguntas como 'qual o estoque do produto X', 'tem em estoque', 'quantidade disponível de X'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome_produto": {"type": "string", "description": "Nome ou parte do nome do produto a buscar"},
                "codigo_produto": {"type": "string", "description": "Código do produto no OMIE (opcional)"}
            }
        }
    }
]

def executar_tool(name, inputs, api, consolidado):
    if consolidado:
        fns = {
            "listar_contas_receber": lambda: consolidar_contas_receber(**inputs),
            "listar_contas_pagar": lambda: consolidar_contas_pagar(**inputs),
            "listar_pedidos_venda": lambda: consolidar_pedidos(**{k:v for k,v in inputs.items() if k=="dias"}),
            "listar_notas_fiscais": lambda: {"notas": "Use empresa específica para listar NFs"},
            "buscar_boleto_por_nf": lambda: {"erro": "Selecione uma empresa específica para boletos"},
            "consultar_cliente": lambda: api.consultar_cliente(**inputs),
            "resumo_financeiro": lambda: consolidar_resumo(),
            "consultar_estoque": lambda: consolidar_estoque(**inputs),
        }
    else:
        fns = {
            "listar_contas_receber": lambda: api.listar_contas_receber(**inputs),
            "listar_contas_pagar": lambda: api.listar_contas_pagar(**inputs),
            "listar_pedidos_venda": lambda: api.listar_pedidos_venda(**inputs),
            "listar_notas_fiscais": lambda: api.listar_notas_fiscais(**inputs),
            "buscar_boleto_por_nf": lambda: api.buscar_boleto_por_nf(**inputs),
            "consultar_cliente": lambda: api.consultar_cliente(**inputs),
            "resumo_financeiro": lambda: api.resumo_financeiro(),
            "consultar_estoque": lambda: api.consultar_estoque(**inputs),
        }
    return fns[name]() if name in fns else {"erro": "Ferramenta não encontrada"}

def chat_com_claude(messages, api, consolidado):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    empresa_ctx = "Formma Componentes e IDDEA (visão consolidada)" if consolidado else api.empresa
    system = f"""Você é um assistente financeiro integrado ao ERP OMIE da empresa: {empresa_ctx}.
Responda sempre em português, de forma clara e objetiva.
Formate valores em reais (R$), datas em formato brasileiro (DD/MM/AAAA).
Organize informações em listas quando houver múltiplos itens.
Quando houver dados de múltiplas empresas, sempre indique a qual empresa cada informação pertence (campo _empresa).

Quando o usuário pedir BOLETO em PDF de uma NF específica:
- Use buscar_boleto_por_nf para obter os dados
- Ao final da resposta inclua: __BOLETO_PDF__:{{"numero_nf":"XXXX"}}

Quando o usuário pedir DANFE ou PDF de NF:
- Use listar_notas_fiscais para obter a chave_nfe
- Ao final da resposta inclua: __DANFE_LINK__:{{"numero_nf":"XXXX","chave_nfe":"XXXXX","link":"https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=completa&nfe=XXXXX"}}

Quando o usuário pedir RELATÓRIO em PDF:
- Busque os dados e ao final inclua: __RELATORIO_PDF__:{{"titulo":"Título","tipo":"contas_receber"}}
"""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        tools=TOOLS,
        messages=messages
    )

    tool_data = {}
    while response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                resultado = executar_tool(block.name, block.input, api, consolidado)
                tool_data[block.name] = resultado
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(resultado, ensure_ascii=False)
                })
        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": tool_results}
        ]
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system,
            tools=TOOLS,
            messages=messages
        )

    texto = "".join(b.text for b in response.content if hasattr(b, "text"))
    return texto, tool_data

def extrair_dados_de_texto(texto: str) -> dict:
    """Usa Claude para extrair dados de lançamento a partir de texto livre."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    hoje = datetime.today().strftime("%d/%m/%Y")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": f"""Hoje é {hoje}. Extraia os dados de lançamento do texto abaixo e retorne APENAS um JSON válido:
{{
  "beneficiario": "nome do fornecedor mencionado ou null",
  "valor": 0.00,
  "data_vencimento": "DD/MM/AAAA ou null",
  "data_previsao": "DD/MM/AAAA ou null",
  "numero_documento": "número do documento ou null",
  "observacao": "descrição/observação mencionada ou null"
}}
Converta datas relativas (ex: 'amanhã', 'sexta', 'próximo dia 10') para DD/MM/AAAA considerando a data de hoje.
Texto: {texto}"""
        }]
    )
    texto_resp = response.content[0].text.strip()
    if "```" in texto_resp:
        texto_resp = texto_resp.split("```")[1].replace("json", "").strip()
    return json.loads(texto_resp)

def extrair_boleto_com_claude(arquivo_bytes: bytes, mime: str) -> dict:
    """Usa Claude Vision para extrair dados de um boleto (imagem ou PDF)."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    b64 = base64.standard_b64encode(arquivo_bytes).decode("utf-8")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": b64}
                },
                {
                    "type": "text",
                    "text": """Analise este boleto bancário e extraia as informações. Retorne APENAS um JSON válido com os campos:
{
  "beneficiario": "nome do beneficiário/fornecedor",
  "valor": 0.00,
  "data_vencimento": "DD/MM/AAAA",
  "numero_documento": "número do documento/nosso número",
  "codigo_barras": "linha digitável completa se visível",
  "banco": "nome do banco"
}
Se algum campo não estiver visível, use null."""
                }
            ]
        }]
    )
    texto = response.content[0].text.strip()
    # Remove markdown se houver
    if "```" in texto:
        texto = texto.split("```")[1].replace("json", "").strip()
    return json.loads(texto)

def processar_acoes_pdf(texto: str, tool_data: dict):
    linhas = texto.split("\n")
    texto_limpo, acoes = [], []
    for linha in linhas:
        for prefixo in ["__BOLETO_PDF__:", "__DANFE_LINK__:", "__RELATORIO_PDF__:"]:
            if linha.startswith(prefixo):
                try:
                    dados = json.loads(linha.replace(prefixo, ""))
                    tipo = prefixo.strip("_:").lower()
                    acoes.append((tipo, dados))
                except:
                    pass
                break
        else:
            texto_limpo.append(linha)
    return "\n".join(texto_limpo), acoes

def renderizar_acoes(acoes: list):
    for tipo, dados in acoes:
        if tipo == "boleto_pdf":
            num_nf = dados.get("numero_nf", "")
            _api = st.session_state.get("_api_atual") or get_api(list(EMPRESAS.keys())[0])
            result = _api.buscar_boleto_por_nf(num_nf)
            boletos = result.get("boletos", [])
            if boletos:
                for i, conta in enumerate(boletos):
                    parcela = conta.get("numero_parcela", str(i+1))
                    pdf_bytes = gerar_boleto_pdf(conta)
                    st.download_button(
                        label=f"📄 Baixar Boleto NF {num_nf} — Parcela {parcela}",
                        data=pdf_bytes,
                        file_name=f"boleto_nf{num_nf}_{parcela.replace('/','-')}.pdf",
                        mime="application/pdf",
                        key=f"bol_{num_nf}_{i}_{int(time.time())}"
                    )
            else:
                st.warning(f"Boleto da NF {num_nf} não encontrado.")

        elif tipo == "danfe_link":
            num_nf = dados.get("numero_nf", "")
            link = dados.get("link", "")
            chave = dados.get("chave_nfe", "")
            if link:
                st.markdown(f"🔗 **[Abrir DANFE da NF {num_nf} no portal SEFAZ]({link})**")
                if chave:
                    st.caption(f"Chave: `{chave}`")

        elif tipo == "relatorio_pdf":
            titulo = dados.get("titulo", "Relatorio")
            tipo_rel = dados.get("tipo", "contas_receber")
            with st.spinner("Gerando PDF..."):
                if tipo_rel == "contas_receber":
                    _api = st.session_state.get("_api_atual") or get_api(list(EMPRESAS.keys())[0])
                    contas = _api.listar_contas_receber(60, "").get("conta_receber_cadastro", [])
                    cols = ["numero_documento_fiscal", "data_vencimento", "valor_documento", "status_titulo"]
                else:
                    _api = st.session_state.get("_api_atual") or get_api(list(EMPRESAS.keys())[0])
                    contas = _api.listar_contas_pagar(60, "").get("conta_pagar_cadastro", [])
                    cols = ["numero_documento", "data_vencimento", "valor_documento", "status_titulo"]
                linhas = [{c: str(x.get(c, "")) for c in cols} for x in contas]
                pdf_bytes = gerar_relatorio_pdf(titulo, linhas, cols)
                st.download_button(
                    label=f"📊 Baixar: {titulo}",
                    data=pdf_bytes,
                    file_name=f"relatorio_{tipo_rel}.pdf",
                    mime="application/pdf",
                    key=f"rel_{tipo_rel}_{int(time.time())}"
                )

# ── PÁGINA: LANÇAR CONTA A PAGAR ────────────────────────────────────────────

def pagina_lancar_conta_pagar(api):
    st.header("📥 Lançar Conta a Pagar")

    modo = st.radio("Como deseja informar?", ["📎 Enviar foto do boleto", "✏️ Digitar as informações"], horizontal=True)

    dados_extraidos = st.session_state.get("boleto_extraido", {})

    if modo == "📎 Enviar foto do boleto":
        arquivo = st.file_uploader(
            "Anexar boleto (JPG, PNG ou PDF)",
            type=["jpg", "jpeg", "png", "pdf"],
            help="Foto, print ou PDF do boleto"
        )
        if arquivo and not dados_extraidos:
            with st.spinner("Lendo boleto com IA..."):
                try:
                    ext = arquivo.name.split(".")[-1].lower()
                    bytes_lidos = arquivo.read()
                    # PDF: converte 1ª página em imagem para Claude Vision
                    if ext == "pdf":
                        import fitz
                        doc = fitz.open(stream=bytes_lidos, filetype="pdf")
                        pix = doc[0].get_pixmap(dpi=150)
                        img_bytes = pix.tobytes("png")
                        mime = "image/png"
                    else:
                        img_bytes = bytes_lidos
                        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(ext, "image/jpeg")
                    dados = extrair_boleto_com_claude(img_bytes, mime)
                    st.session_state["boleto_extraido"] = dados
                    st.session_state["boleto_arquivo_bytes"] = bytes_lidos
                    st.session_state["boleto_arquivo_nome"] = arquivo.name
                    dados_extraidos = dados
                    st.success("Dados extraídos! Confira e complete abaixo.")
                except Exception as e:
                    st.error(f"Erro ao ler boleto: {e}")
        if arquivo:
            arquivo.seek(0)
            ext = arquivo.name.split(".")[-1].lower()
            if ext == "pdf":
                st.info(f"📄 PDF anexado: {arquivo.name}")
            else:
                st.image(arquivo, caption="Boleto enviado", width=400)

    else:
        texto_livre = st.text_area(
            "Descreva o lançamento em texto livre:",
            placeholder="Ex: Conta de luz da Enel, vence dia 15/06, valor R$ 450,00, pagar no dia 14/06, categoria energia elétrica",
            height=100
        )
        if st.button("🔍 Extrair dados do texto") and texto_livre:
            with st.spinner("Interpretando..."):
                try:
                    dados = extrair_dados_de_texto(texto_livre)
                    st.session_state["boleto_extraido"] = dados
                    dados_extraidos = dados
                    st.success("Dados identificados! Confira e complete abaixo.")
                except Exception as e:
                    st.error(f"Erro ao interpretar texto: {e}")

    st.divider()
    st.subheader("Dados do Lançamento")

    # Busca fornecedor
    col1, col2 = st.columns([3, 1])
    with col1:
        busca_fornecedor = st.text_input(
            "🔍 Fornecedor (buscar pelo nome)",
            value=dados_extraidos.get("beneficiario", "") or ""
        )
    with col2:
        st.write("")
        st.write("")
        buscar_btn = st.button("Buscar", use_container_width=True)

    fornecedor_selecionado = st.session_state.get("fornecedor_sel", None)

    if buscar_btn and busca_fornecedor:
        with st.spinner("Buscando..."):
            resultado = api.buscar_fornecedor(busca_fornecedor)
            st.session_state["fornecedores_encontrados"] = resultado

    fornecedores = st.session_state.get("fornecedores_encontrados", [])
    if fornecedores:
        opcoes = {f"{f['nome']} ({f['fantasia']})": f for f in fornecedores}
        escolha = st.selectbox("Selecione o fornecedor:", list(opcoes.keys()))
        fornecedor_selecionado = opcoes[escolha]
        st.session_state["fornecedor_sel"] = fornecedor_selecionado

    if fornecedor_selecionado:
        st.success(f"Fornecedor: **{fornecedor_selecionado['nome']}** (código {fornecedor_selecionado['codigo']})")

    st.divider()

    # Valor e datas
    col_v, col_venc, col_prev = st.columns(3)

    valor_str = str(dados_extraidos.get("valor") or "")
    try:
        valor_default = float(valor_str) if valor_str else 0.0
    except:
        valor_default = 0.0

    with col_v:
        valor = st.number_input("Valor (R$)", min_value=0.0, value=valor_default, format="%.2f")

    def parse_data(s):
        if not s:
            return date.today() + timedelta(days=7)
        for fmt in ["%d/%m/%Y", "%Y-%m-%d"]:
            try:
                return datetime.strptime(s, fmt).date()
            except:
                pass
        return date.today() + timedelta(days=7)

    with col_venc:
        vencimento = st.date_input("Vencimento", value=parse_data(dados_extraidos.get("data_vencimento")))

    with col_prev:
        previsao = st.date_input("Data Prevista para Pagamento", value=parse_data(dados_extraidos.get("data_previsao") or dados_extraidos.get("data_vencimento")))

    # Categoria (cache por empresa)
    cat_key = f"categorias_{api.empresa}"
    if cat_key not in st.session_state:
        with st.spinner("Carregando categorias..."):
            st.session_state[cat_key] = api.listar_categorias_despesa()
    categorias = st.session_state[cat_key]
    if categorias:
        cat_opcoes = {f"{c['codigo']} - {c['descricao']}": c["codigo"] for c in categorias}
        cat_escolhida = st.selectbox("Categoria", list(cat_opcoes.keys()))
        codigo_categoria = cat_opcoes.get(cat_escolhida, categorias[0]["codigo"])
    else:
        st.warning("Não foi possível carregar as categorias do OMIE.")
        codigo_categoria = st.text_input("Código da Categoria (manual)", placeholder="Ex: 2.04.99")

    # Número do documento e observação
    col_d, col_o = st.columns(2)
    with col_d:
        num_doc = st.text_input("Número do Documento", value=dados_extraidos.get("numero_documento") or "")
    with col_o:
        obs = st.text_input("Observação", value=dados_extraidos.get("observacao") or "", placeholder="Ex: Conta de luz de junho")

    codigo_barras = dados_extraidos.get("codigo_barras") or ""

    st.divider()

    # Botão de lançamento
    pode_lancar = fornecedor_selecionado and valor > 0
    if not pode_lancar:
        st.info("Preencha o fornecedor e o valor para lançar.")

    if st.button("✅ Lançar no OMIE", type="primary", disabled=not pode_lancar, use_container_width=True):
        with st.spinner("Lançando no OMIE..."):
            resultado = api.lancar_conta_pagar(
                codigo_fornecedor=fornecedor_selecionado["codigo"],
                valor=valor,
                data_vencimento=vencimento.strftime("%d/%m/%Y"),
                data_previsao=previsao.strftime("%d/%m/%Y"),
                codigo_categoria=codigo_categoria,
                numero_documento=num_doc,
                observacao=obs,
                codigo_barras=codigo_barras,
            )
        if resultado.get("codigo_status") == "0":
            cod_omie = resultado.get("codigo_lancamento_omie")
            st.success(f"✅ Lançado com sucesso! Código OMIE: `{cod_omie}`")
            # Anexa boleto automaticamente se veio por imagem
            arquivo_bytes = st.session_state.get("boleto_arquivo_bytes")
            arquivo_nome = st.session_state.get("boleto_arquivo_nome", "boleto.jpg")
            if arquivo_bytes and cod_omie:
                with st.spinner("Anexando boleto ao lançamento..."):
                    ext = arquivo_nome.split(".")[-1].lower()
                    ra = api.anexar_arquivo("conta-pagar", cod_omie, arquivo_nome, arquivo_bytes)
                    if "faultstring" not in ra:
                        st.success("📎 Boleto anexado ao lançamento no OMIE.")
                    else:
                        st.warning(f"Lançado, mas não foi possível anexar o boleto: {ra.get('faultstring','')}")
            # Limpa estado
            for k in ["boleto_extraido", "fornecedores_encontrados", "fornecedor_sel", "boleto_arquivo_bytes", "boleto_arquivo_nome"]:
                st.session_state.pop(k, None)
        else:
            st.error(f"Erro ao lançar: {resultado.get('faultstring', resultado)}")


# ── PÁGINA: BAIXAR PAGAMENTO ─────────────────────────────────────────────────

def pagina_baixar_pagamento(api):
    st.header("✅ Baixar Pagamento")
    st.caption("Marque uma conta como paga e anexe o comprovante.")

    # Filtro de data
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        data_ini = st.date_input("Vencimento de:", value=date.today() - timedelta(days=60))
    with col_f2:
        data_fim = st.date_input("até:", value=date.today() + timedelta(days=60))
    buscar = st.button("🔍 Buscar", use_container_width=True, type="primary")

    chave_cache = f"contas_pagar_{api.empresa}_{data_ini}_{data_fim}"

    if buscar:
        with st.spinner("Carregando contas..."):
            filtradas = api.listar_contas_pagar_por_vencimento(data_ini, data_fim, "EMABERTO")
            st.session_state[chave_cache] = filtradas

    contas = st.session_state.get(chave_cache, [])

    if not contas:
        st.info("Nenhuma conta em aberto no período selecionado.")
        return

    st.caption(f"{len(contas)} conta(s) encontrada(s)")

    # Monta opções para seleção
    opcoes = {}
    for c in contas:
        cod = c["codigo_lancamento_omie"]
        num_doc = c.get("numero_documento", "") or c.get("numero_documento_fiscal", "")
        venc = c.get("data_vencimento", "")
        val = c.get("valor_documento", 0)
        nome = c.get("nome_fornecedor", "") or str(c.get("codigo_cliente_fornecedor", ""))
        val_fmt = f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        label = f"{nome} | Doc: {num_doc} | Venc: {venc} | {val_fmt}"
        opcoes[label] = c

    escolha = st.selectbox("Selecione a conta:", list(opcoes.keys()))
    conta_sel = opcoes[escolha]
    cod_lancamento = conta_sel["codigo_lancamento_omie"]
    valor_original = conta_sel.get("valor_documento", 0)

    st.divider()

    # Conta corrente
    cc_key = f"contas_correntes_{api.empresa}"
    if cc_key not in st.session_state:
        st.session_state[cc_key] = api.listar_contas_correntes()
    cc_list = st.session_state[cc_key]
    cc_opcoes = {f"{c['descricao']} ({c['banco']})": c["codigo"] for c in cc_list}
    cc_escolhida = st.selectbox("Conta bancária utilizada:", list(cc_opcoes.keys()))
    cod_conta_corrente = cc_opcoes[cc_escolhida]

    col_v, col_d = st.columns(2)
    with col_v:
        valor_pago = st.number_input("Valor pago (R$)", min_value=0.0, value=float(valor_original), format="%.2f")
    with col_d:
        data_pag = st.date_input("Data do pagamento", value=date.today())

    # Comprovante
    comprovante = st.file_uploader(
        "📎 Anexar comprovante (JPG, PNG ou PDF)",
        type=["jpg", "jpeg", "png", "pdf"],
        help="Foto ou PDF do comprovante de pagamento"
    )
    if comprovante:
        comprovante.seek(0)
        if comprovante.name.lower().endswith(".pdf"):
            st.info(f"📄 PDF anexado: {comprovante.name}")
        else:
            st.image(comprovante, caption="Comprovante", width=300)

    st.divider()

    if st.button("✅ Confirmar Pagamento", type="primary", use_container_width=True):
        with st.spinner("Lançando baixa no OMIE..."):
            r_baixa = api.baixar_pagamento(
                codigo_lancamento=cod_lancamento,
                codigo_conta_corrente=cod_conta_corrente,
                valor=valor_pago,
                data_pagamento=data_pag.strftime("%d/%m/%Y"),
            )

        if r_baixa.get("codigo_status") == "0":
            st.success(f"✅ Pagamento baixado com sucesso! Código baixa: `{r_baixa.get('codigo_baixa')}`")
            # Anexa comprovante se enviado
            if comprovante:
                comprovante.seek(0)
                bytes_comp = comprovante.read()
                with st.spinner("Anexando comprovante..."):
                    ra = api.anexar_arquivo("conta-pagar", cod_lancamento, comprovante.name, bytes_comp)
                    if "faultstring" not in ra:
                        st.success("📎 Comprovante anexado ao lançamento no OMIE.")
                    else:
                        st.warning(f"Baixa feita, mas não foi possível anexar: {ra.get('faultstring','')}")
            # Remove da lista em cache
            chave_cache = f"contas_pagar_{data_ini}_{data_fim}"
            st.session_state[chave_cache] = [
                c for c in st.session_state.get(chave_cache, [])
                if c["codigo_lancamento_omie"] != cod_lancamento
            ]
            st.rerun()
        else:
            st.error(f"Erro: {r_baixa.get('faultstring', r_baixa)}")


# ── PÁGINA: CHAT ─────────────────────────────────────────────────────────────

def pagina_chat(api, consolidado=False, empresa_sel=""):
    st.header("💬 Consultar OMIE")

    chat_key = f"messages_{empresa_sel or api.empresa}"
    hist_key = f"history_{empresa_sel or api.empresa}"
    if chat_key not in st.session_state:
        st.session_state[chat_key] = []
        st.session_state[hist_key] = []
    # Apelidos para compatibilidade com o restante da função
    st.session_state["messages"] = st.session_state[chat_key]
    st.session_state["history"] = st.session_state[hist_key]

    if not st.session_state.messages:
        st.markdown("**Sugestões:**")
        cols = st.columns(2)
        sugestoes = [
            ("📋 Pedidos em aberto", "Quais pedidos estão em aberto?"),
            ("💰 Contas a receber", "Me mostra as contas a receber do mês"),
            ("📄 Notas fiscais recentes", "Liste as últimas notas fiscais emitidas"),
            ("⚠️ Contas atrasadas", "Quais contas estão atrasadas?"),
        ]
        for i, (label, prompt) in enumerate(sugestoes):
            if cols[i % 2].button(label, use_container_width=True):
                st.session_state.messages.append({"role": "user", "content": prompt})
                st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("acoes"):
                renderizar_acoes(msg["acoes"])

    if prompt := st.chat_input("Digite sua pergunta..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Consultando OMIE..."):
                st.session_state.history.append({"role": "user", "content": prompt})
                resposta_bruta, tool_data = chat_com_claude(st.session_state.history, api, consolidado)
                resposta, acoes = processar_acoes_pdf(resposta_bruta, tool_data)
                st.session_state.history.append({"role": "assistant", "content": resposta_bruta})
                st.markdown(resposta)
                if acoes:
                    renderizar_acoes(acoes)
                st.session_state.messages.append({"role": "assistant", "content": resposta, "acoes": acoes})


# ── PÁGINA: PROPOSTA COMERCIAL ───────────────────────────────────────────────

def pagina_proposta(api):
    st.header("📋 Proposta Comercial")
    st.caption("Crie um orçamento/proposta e gere pedido no OMIE.")

    # ── 1. Cliente ────────────────────────────────────────────────────────────
    st.subheader("1. Cliente")
    col_c, col_cb = st.columns([4, 1])
    with col_c:
        busca_cli = st.text_input("Buscar cliente pelo nome", key="prop_busca_cli")
    with col_cb:
        st.write("")
        st.write("")
        if st.button("Buscar", key="prop_btn_cli"):
            with st.spinner("Buscando..."):
                r = api.consultar_cliente(busca_cli)
                st.session_state["prop_clientes"] = r.get("clientes_cadastro", [])

    clientes = st.session_state.get("prop_clientes", [])
    cliente_sel = st.session_state.get("prop_cliente_sel", None)
    if clientes:
        opcoes_cli = {f"{c.get('razao_social','')} ({c.get('nome_fantasia','')})": c for c in clientes}
        escolha_cli = st.selectbox("Selecione o cliente:", list(opcoes_cli.keys()), key="prop_sel_cli")
        cliente_sel = opcoes_cli[escolha_cli]
        st.session_state["prop_cliente_sel"] = cliente_sel
    if cliente_sel:
        st.success(f"✅ {cliente_sel.get('razao_social','')} — código {cliente_sel.get('codigo_cliente_omie','')}")

    st.divider()

    # ── 2. Produtos ───────────────────────────────────────────────────────────
    st.subheader("2. Produtos")
    col_p, col_pb = st.columns([4, 1])
    with col_p:
        busca_prod = st.text_input("Buscar produto pelo nome ou código", key="prop_busca_prod")
    with col_pb:
        st.write("")
        st.write("")
        if st.button("Buscar", key="prop_btn_prod"):
            with st.spinner("Buscando..."):
                st.session_state["prop_produtos_encontrados"] = api.buscar_produtos(busca_prod)

    prods_encontrados = st.session_state.get("prop_produtos_encontrados", [])
    if prods_encontrados:
        opcoes_prod = {f"{p['codigo']} — {p['descricao']}": p for p in prods_encontrados}
        escolha_prod = st.selectbox("Produto:", list(opcoes_prod.keys()), key="prop_sel_prod")
        prod_sel = opcoes_prod[escolha_prod]

        col_q, col_v, col_d, col_add = st.columns([2, 2, 2, 1])
        with col_q:
            qty = st.number_input("Qtd", min_value=0.0, value=1.0, format="%.2f", key="prop_qty")
        with col_v:
            vunit = st.number_input("Vl. Unit (R$)", min_value=0.0,
                                     value=float(prod_sel.get("valor_unitario", 0)), format="%.2f", key="prop_vunit")
        with col_d:
            desc_pct = st.number_input("Desconto %", min_value=0.0, max_value=100.0, value=0.0, format="%.1f", key="prop_desc")
        with col_add:
            st.write("")
            st.write("")
            if st.button("➕ Adicionar", key="prop_add"):
                itens = st.session_state.get("prop_itens", [])
                itens.append({
                    "codigo_produto": prod_sel["codigo_produto"],
                    "codigo": prod_sel["codigo"],
                    "descricao": prod_sel["descricao"],
                    "unidade": prod_sel.get("unidade", "UN"),
                    "quantidade": qty,
                    "valor_unitario": vunit,
                    "desconto": desc_pct,
                })
                st.session_state["prop_itens"] = itens
                st.rerun()

    # Carrinho
    itens = st.session_state.get("prop_itens", [])
    if itens:
        st.markdown("**Itens da proposta:**")
        total = 0
        for i, item in enumerate(itens):
            subtotal = item["quantidade"] * item["valor_unitario"] * (1 - item["desconto"] / 100)
            total += subtotal
            def fmt(v): return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            col_i, col_rm = st.columns([9, 1])
            with col_i:
                st.write(f"**{item['descricao']}** | {item['quantidade']} {item['unidade']} × {fmt(item['valor_unitario'])} | Desc: {item['desconto']}% | **{fmt(subtotal)}**")
            with col_rm:
                if st.button("🗑", key=f"rm_{i}"):
                    itens.pop(i)
                    st.session_state["prop_itens"] = itens
                    st.rerun()

        def fmt(v): return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        st.markdown(f"### Total: {fmt(total)}")

    st.divider()

    # ── 3. Condições ──────────────────────────────────────────────────────────
    st.subheader("3. Condições e Observações")
    col_cp, col_obs = st.columns(2)
    with col_cp:
        cp_key = f"cond_pag_{api.empresa}"
        if cp_key not in st.session_state:
            st.session_state[cp_key] = api.listar_condicoes_pagamento()
        conds = st.session_state[cp_key]
        if conds:
            opcoes_cp = {c["descricao"]: c["codigo"] for c in conds}
            cp_escolha = st.selectbox("Condição de Pagamento:", list(opcoes_cp.keys()), key="prop_cp")
            cod_cp = opcoes_cp[cp_escolha]
            desc_cp = cp_escolha
        else:
            cod_cp = "999"
            desc_cp = st.text_input("Condição de Pagamento", key="prop_cp_txt")
    with col_obs:
        obs = st.text_area("Observações", height=80, key="prop_obs",
                            placeholder="Ex: Validade da proposta: 15 dias. Frete por conta do cliente.")

    st.divider()

    # ── 4. Ações ──────────────────────────────────────────────────────────────
    pode_criar = cliente_sel and itens
    if not pode_criar:
        st.info("Adicione cliente e pelo menos um produto para criar a proposta.")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📋 Criar Pedido no OMIE", type="primary",
                      disabled=not pode_criar, use_container_width=True):
            with st.spinner("Criando pedido no OMIE..."):
                r = api.criar_pedido_proposta(
                    codigo_cliente=cliente_sel["codigo_cliente_omie"],
                    itens=itens,
                    condicao_pagamento=cod_cp,
                    observacao=obs,
                )
            if r.get("codigo_status") == "0" or r.get("numero_pedido"):
                num_ped = r.get("numero_pedido", "")
                st.success(f"✅ Pedido criado no OMIE! Número: **{num_ped}**")
                st.session_state["prop_numero_pedido"] = str(num_ped)
            else:
                st.error(f"Erro: {r.get('faultstring', r)}")

    with col_b:
        if st.button("📄 Baixar PDF da Proposta", disabled=not pode_criar,
                      use_container_width=True):
            num_ped = st.session_state.get("prop_numero_pedido", "")
            pdf_bytes = gerar_proposta_pdf(
                empresa=api.empresa,
                cliente_nome=cliente_sel.get("razao_social", "") if cliente_sel else "",
                itens=itens,
                condicao_pagamento=desc_cp if pode_criar else "",
                observacao=obs,
                numero_pedido=num_ped,
            )
            st.download_button(
                label="⬇️ Clique para baixar",
                data=pdf_bytes,
                file_name=f"proposta_{cliente_sel.get('razao_social','')[:20].replace(' ','_')}_{datetime.today().strftime('%d%m%Y')}.pdf",
                mime="application/pdf",
                key=f"dl_prop_{int(time.time())}"
            )

    # Limpar
    if itens and st.button("🗑 Limpar proposta", use_container_width=True):
        for k in ["prop_itens", "prop_cliente_sel", "prop_clientes",
                  "prop_produtos_encontrados", "prop_numero_pedido"]:
            st.session_state.pop(k, None)
        st.rerun()


# ── LAYOUT PRINCIPAL ─────────────────────────────────────────────────────────

st.set_page_config(page_title="Assistente", page_icon="🏢", layout="centered")

# Cores da identidade IDDEA
TAUPE   = "#C4B8B0"
BROWN   = "#3D291E"
BROWN_L = "#6B4F43"
CREAM   = "#F5F0EC"
WHITE   = "#FFFFFF"

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;600&family=Lato:wght@300;400;700&display=swap');

    /* Fundo geral */
    .stApp {{ background-color: {CREAM}; }}
    .block-container {{ padding-top: 1.5rem; }}

    /* Tipografia */
    html, body, [class*="css"] {{ font-family: 'Lato', sans-serif; color: {BROWN}; }}
    h1, h2, h3 {{ font-family: 'Cormorant Garamond', serif; color: {BROWN}; font-weight: 300; letter-spacing: 2px; }}

    /* Header customizado */
    .app-header {{
        background: {TAUPE};
        padding: 28px 24px 20px;
        border-radius: 12px;
        margin-bottom: 20px;
        text-align: center;
    }}
    .app-header .logo-text {{
        font-family: 'Cormorant Garamond', serif;
        font-size: 2.8rem;
        font-weight: 300;
        color: {BROWN};
        letter-spacing: 8px;
        line-height: 1;
    }}
    .app-header .logo-sub {{
        font-family: 'Lato', sans-serif;
        font-size: 0.65rem;
        letter-spacing: 6px;
        color: {BROWN_L};
        margin-top: 4px;
    }}
    .app-header .app-title {{
        font-family: 'Lato', sans-serif;
        font-size: 0.8rem;
        letter-spacing: 3px;
        color: {BROWN_L};
        margin-top: 14px;
        text-transform: uppercase;
    }}

    /* Seletor de empresa */
    .empresa-bar {{
        display: flex;
        gap: 8px;
        justify-content: center;
        margin: 12px 0 20px;
        flex-wrap: wrap;
    }}
    .empresa-btn {{
        padding: 6px 18px;
        border-radius: 20px;
        font-size: 12px;
        letter-spacing: 1px;
        font-family: 'Lato', sans-serif;
        cursor: pointer;
        border: 1px solid {BROWN_L};
        background: transparent;
        color: {BROWN};
        text-transform: uppercase;
    }}
    .empresa-btn.ativo {{
        background: {BROWN};
        color: {WHITE};
        border-color: {BROWN};
    }}

    /* Radio buttons estilizados */
    div[data-testid="stRadio"] label {{
        font-size: 13px;
        letter-spacing: 1px;
        text-transform: uppercase;
        color: {BROWN};
        font-family: 'Lato', sans-serif;
    }}
    div[data-testid="stRadio"] > div {{
        gap: 8px;
    }}

    /* Botões */
    .stButton > button {{
        background: {BROWN} !important;
        color: {WHITE} !important;
        border: none !important;
        border-radius: 4px !important;
        font-family: 'Lato', sans-serif !important;
        letter-spacing: 1.5px !important;
        font-size: 13px !important;
        text-transform: uppercase !important;
        min-height: 44px;
        transition: opacity 0.2s;
    }}
    .stButton > button:hover {{ opacity: 0.85 !important; }}
    .stButton > button[disabled] {{ background: #ccc !important; }}

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {{
        background: transparent;
        border-bottom: 1px solid {TAUPE};
        gap: 0;
    }}
    .stTabs [data-baseweb="tab"] {{
        font-family: 'Lato', sans-serif;
        font-size: 11px;
        letter-spacing: 2px;
        text-transform: uppercase;
        color: {BROWN_L};
        padding: 10px 14px;
        border: none;
        background: transparent;
    }}
    .stTabs [aria-selected="true"] {{
        color: {BROWN} !important;
        border-bottom: 2px solid {BROWN} !important;
        font-weight: 700;
    }}

    /* Inputs */
    input, textarea, select {{
        font-size: 15px !important;
        border-radius: 4px !important;
        border-color: {TAUPE} !important;
        font-family: 'Lato', sans-serif !important;
    }}
    input:focus, textarea:focus {{ border-color: {BROWN} !important; box-shadow: none !important; }}

    /* Cards / containers */
    .stAlert {{ border-radius: 8px; border-left: 3px solid {BROWN}; }}
    div[data-testid="stExpander"] {{ border: 1px solid {TAUPE}; border-radius: 8px; }}

    /* Chat */
    .stChatMessage {{ border-radius: 10px; }}
    .stChatInputContainer textarea {{
        font-size: 15px !important;
        font-family: 'Lato', sans-serif !important;
    }}

    /* Selectbox */
    div[data-baseweb="select"] {{ border-radius: 4px !important; }}

    /* Divider */
    hr {{ border-color: {TAUPE}; }}

    /* Mobile */
    @media (max-width: 640px) {{
        .block-container {{ padding: 0.75rem; }}
        .app-header .logo-text {{ font-size: 2rem; }}
    }}
</style>
""", unsafe_allow_html=True)

# ── Header com logo ───────────────────────────────────────────────────────────
st.markdown(f"""
<div class="app-header">
    <div class="logo-text">IDDEA<span style="font-size:1.8rem">·</span></div>
    <div class="logo-sub">C O M P O N E N T E S</div>
    <div class="app-title">Assistente</div>
</div>
""", unsafe_allow_html=True)

# ── Seletor de empresa ────────────────────────────────────────────────────────
opcoes_empresa = list(EMPRESAS.keys()) + ["🔀 Consolidado"]
empresa_sel = st.radio(
    "Empresa",
    opcoes_empresa,
    horizontal=True,
    key="empresa_ativa",
    label_visibility="collapsed"
)

consolidado = empresa_sel == "🔀 Consolidado"
api = get_api(list(EMPRESAS.keys())[0]) if consolidado else get_api(empresa_sel)
st.session_state["_api_atual"] = api

st.divider()

aba = st.tabs(["💬 Consultar", "📋 Proposta", "📥 Lançar Conta", "✅ Baixar Pagamento"])

with aba[0]:
    pagina_chat(api, consolidado, empresa_sel)

with aba[1]:
    if consolidado:
        st.info("Selecione uma empresa específica para criar propostas.")
    else:
        pagina_proposta(api)

with aba[2]:
    if consolidado:
        st.info("Selecione uma empresa específica para lançar contas a pagar.")
    else:
        pagina_lancar_conta_pagar(api)

with aba[3]:
    if consolidado:
        st.info("Selecione uma empresa específica para baixar pagamentos.")
    else:
        pagina_baixar_pagamento(api)
