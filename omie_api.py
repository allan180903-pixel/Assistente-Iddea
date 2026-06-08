import requests
import json
import os
import time
import base64
import hashlib
import zipfile
import io
from datetime import datetime, timedelta

BASE_URL = "https://app.omie.com.br/api/v1"

EMPRESAS = {
    "Formma Componentes": {
        "app_key": os.environ.get("FORMMA_APP_KEY", ""),
        "app_secret": os.environ.get("FORMMA_APP_SECRET", ""),
        "cor": "#1a3a5c",
    },
    "IDDEA": {
        "app_key": os.environ.get("IDDEA_APP_KEY", ""),
        "app_secret": os.environ.get("IDDEA_APP_SECRET", ""),
        "cor": "#2d6a4f",
    },
}

# ── Cache de clientes por empresa ────────────────────────────────────────────

_CACHE_DIR = os.path.dirname(__file__)

def _cache_path(empresa: str, tipo: str) -> str:
    slug = empresa.lower().replace(" ", "_")
    return os.path.join(_CACHE_DIR, f"{tipo}_{slug}.json")

def _carregar_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

def _salvar_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False)


# ── Classe principal ─────────────────────────────────────────────────────────

class OmieAPI:
    def __init__(self, empresa: str):
        if empresa not in EMPRESAS:
            raise ValueError(f"Empresa desconhecida: {empresa}")
        self.empresa = empresa
        cfg = EMPRESAS[empresa]
        self.app_key = cfg["app_key"]
        self.app_secret = cfg["app_secret"]
        # Cache de nomes de clientes
        self._clientes: dict = _carregar_json(_cache_path(empresa, "clientes"))

    def _call(self, endpoint: str, call: str, params: dict) -> dict:
        url = f"{BASE_URL}/{endpoint}/"
        payload = {
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "call": call,
            "param": [params],
        }
        r = requests.post(url, json=payload, timeout=30)
        return r.json()

    def _nome(self, codigo: int) -> str:
        key = str(codigo)
        if key not in self._clientes:
            r = self._call("geral/clientes", "ConsultarCliente", {"codigo_cliente_omie": codigo})
            nome = r.get("razao_social") or r.get("nome_fantasia") or key
            self._clientes[key] = nome
            _salvar_json(_cache_path(self.empresa, "clientes"), self._clientes)
        return self._clientes[key]

    def sincronizar_clientes(self) -> int:
        pagina = 1
        while True:
            r = self._call("geral/clientes", "ListarClientes", {
                "pagina": pagina, "registros_por_pagina": 200, "apenas_importado_api": "N"
            })
            for c in r.get("clientes_cadastro", []):
                cod = str(c.get("codigo_cliente_omie", ""))
                nome = c.get("razao_social") or c.get("nome_fantasia") or cod
                if cod:
                    self._clientes[cod] = nome
            if pagina >= r.get("total_de_paginas", 1):
                break
            pagina += 1
        _salvar_json(_cache_path(self.empresa, "clientes"), self._clientes)
        return len(self._clientes)

    def listar_contas_receber(self, dias_vencimento=30, status="EMABERTO"):
        hoje = datetime.today()
        params = {
            "pagina": 1, "registros_por_pagina": 50, "apenas_importado_api": "N",
            "filtrar_por_data_de": (hoje - timedelta(days=60)).strftime("%d/%m/%Y"),
            "filtrar_por_data_ate": (hoje + timedelta(days=dias_vencimento)).strftime("%d/%m/%Y"),
        }
        if status:
            params["filtrar_por_status"] = status
        result = self._call("financas/contareceber", "ListarContasReceber", params)
        for c in result.get("conta_receber_cadastro", []):
            c["nome_cliente"] = self._nome(c.get("codigo_cliente_fornecedor", 0))
            c["_empresa"] = self.empresa
        return result

    def listar_contas_pagar(self, dias_vencimento=30, status="EMABERTO"):
        hoje = datetime.today()
        params = {
            "pagina": 1, "registros_por_pagina": 50, "apenas_importado_api": "N",
            "filtrar_por_data_de": (hoje - timedelta(days=60)).strftime("%d/%m/%Y"),
            "filtrar_por_data_ate": (hoje + timedelta(days=dias_vencimento)).strftime("%d/%m/%Y"),
        }
        if status:
            params["filtrar_por_status"] = status
        result = self._call("financas/contapagar", "ListarContasPagar", params)
        for c in result.get("conta_pagar_cadastro", []):
            c["nome_fornecedor"] = self._nome(c.get("codigo_cliente_fornecedor", 0))
            c["_empresa"] = self.empresa
        return result

    def listar_contas_pagar_por_vencimento(self, data_ini, data_fim, status="EMABERTO"):
        """Busca todas as contas e filtra por vencimento no Python."""
        todas = []
        pagina = 1
        while True:
            r = self._call("financas/contapagar", "ListarContasPagar", {
                "pagina": pagina, "registros_por_pagina": 100, "apenas_importado_api": "N",
                "filtrar_por_status": status,
            })
            lote = r.get("conta_pagar_cadastro", [])
            todas.extend(lote)
            if pagina >= r.get("total_de_paginas", 1):
                break
            pagina += 1

        def parse_d(s):
            try: return datetime.strptime(s, "%d/%m/%Y").date()
            except: return None

        filtradas = [c for c in todas if (d := parse_d(c.get("data_vencimento", ""))) and data_ini <= d <= data_fim]
        for c in filtradas:
            c["nome_fornecedor"] = self._nome(c.get("codigo_cliente_fornecedor", 0))
            c["_empresa"] = self.empresa
        return filtradas

    def listar_pedidos_venda(self, dias=30, status=""):
        hoje = datetime.today()
        params = {
            "pagina": 1, "registros_por_pagina": 50, "apenas_importado_api": "N",
            "filtrar_por_data_de": (hoje - timedelta(days=dias)).strftime("%d/%m/%Y"),
            "filtrar_por_data_ate": hoje.strftime("%d/%m/%Y"),
        }
        if status:
            params["etapa"] = status
        result = self._call("produtos/pedido", "ListarPedidos", params)
        for p in result.get("pedido_venda_produto", []):
            cod = p.get("cabecalho", {}).get("codigo_cliente", 0)
            p["cabecalho"]["nome_cliente"] = self._nome(cod) if cod else ""
            p["cabecalho"]["_empresa"] = self.empresa
        return result

    def listar_notas_fiscais(self, dias=60):
        result = self.listar_contas_receber(dias_vencimento=dias, status="")
        contas = result.get("conta_receber_cadastro", [])
        nfs, seen = [], set()
        for c in contas:
            num_nf = c.get("numero_documento_fiscal", "")
            if num_nf and num_nf not in seen and c.get("codigo_tipo_documento") == "NFE":
                seen.add(num_nf)
                chave = c.get("chave_nfe", "")
                nfs.append({
                    "numero_nf": num_nf,
                    "chave_nfe": chave,
                    "data_emissao": c.get("data_emissao", ""),
                    "valor": c.get("valor_documento", 0),
                    "numero_pedido": c.get("numero_pedido", ""),
                    "nome_cliente": c.get("nome_cliente", ""),
                    "_empresa": self.empresa,
                    "link_sefaz": f"https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=completa&nfe={chave}",
                })
        return {"notas_fiscais": nfs, "total": len(nfs)}

    def buscar_boleto_por_nf(self, numero_nf: str):
        result = self.listar_contas_receber(dias_vencimento=365, status="")
        contas = result.get("conta_receber_cadastro", [])
        encontradas = [c for c in contas if
                       c.get("numero_documento_fiscal", "") == str(numero_nf).zfill(8) or
                       c.get("numero_documento_fiscal", "").lstrip("0") == str(numero_nf).lstrip("0")]
        return {"boletos": encontradas, "total": len(encontradas)}

    def _listar_todos_produtos(self) -> list:
        """Busca todos os produtos paginando."""
        todos = []
        pagina = 1
        while True:
            r = self._call("geral/produtos", "ListarProdutos", {
                "pagina": pagina, "registros_por_pagina": 500,
                "filtrar_apenas_omiepdv": "N",
            })
            lote = r.get("produto_servico_cadastro", [])
            todos.extend(lote)
            if pagina >= r.get("total_de_paginas", 1):
                break
            pagina += 1
        return todos

    def buscar_produtos(self, nome: str = "", codigo: str = ""):
        """Busca produtos cadastrados no OMIE por nome ou código."""
        todos = self._listar_todos_produtos()
        resultado = []
        for p in todos:
            desc = p.get("descricao", "")
            cod = p.get("codigo", "")
            termo = nome or codigo
            if termo:
                if termo.lower() not in desc.lower() and termo.lower() not in cod.lower():
                    continue
            resultado.append({
                "codigo_produto": p.get("codigo_produto", 0),
                "codigo": cod,
                "descricao": desc,
                "unidade": p.get("unidade", "UN"),
                "valor_unitario": p.get("valor_unitario", 0),
                "estoque_atual": p.get("quantidade_estoque", 0),
            })
        return resultado

    def listar_condicoes_pagamento(self):
        """Lista condições de pagamento cadastradas."""
        r = self._call("geral/cparcelamento", "ListarCondicoesPagamento", {
            "pagina": 1, "registros_por_pagina": 50
        })
        return [
            {"codigo": c.get("cCodigo", ""), "descricao": c.get("cDescricao", "")}
            for c in r.get("cadastros", [])
        ]

    def criar_pedido_proposta(self, codigo_cliente: int, itens: list,
                               condicao_pagamento: str = "", observacao: str = "",
                               codigo_categoria: str = ""):
        """Cria um pedido de venda como proposta/orçamento no OMIE."""
        hoje = datetime.today().strftime("%d/%m/%Y")
        det = []
        for i, item in enumerate(itens, 1):
            det.append({
                "ide": {"nItem": i},
                "produto": {
                    "codigo_produto": item["codigo_produto"],
                    "quantidade": item["quantidade"],
                    "valor_unitario": item["valor_unitario"],
                    "percentual_desconto": item.get("desconto", 0),
                }
            })
        payload = {
            "cabecalho": {
                "codigo_cliente": codigo_cliente,
                "data_previsao": hoje,
                "etapa": "10",  # Etapa inicial = proposta/orçamento
                "codigo_parcela": condicao_pagamento or "999",
            },
            "det": det,
            "informacoes_adicionais": {
                "codigo_categoria": codigo_categoria or "1.01.99",
                "observacoes": observacao,
                "consumidor_final": "N",
            }
        }
        return self._call("produtos/pedido", "IncluirPedido", payload)

    def _posicao_estoque(self, codigo_produto_omie: int) -> dict:
        """Consulta saldo real de estoque de um produto via PosicaoEstoque."""
        hoje = datetime.today().strftime("%d/%m/%Y")
        try:
            r = self._call("estoque/consulta", "PosicaoEstoque", {
                "nCodProd": codigo_produto_omie,
                "data": hoje,
            })
            locais = r.get("estoque", [])
            fisico = sum(float(l.get("nQtdFisico", 0)) for l in locais)
            reservado = sum(float(l.get("nQtdReservado", 0)) for l in locais)
            disponivel = sum(float(l.get("nQtdDisponivel", 0)) for l in locais)
            if fisico or disponivel:
                return {"fisico": fisico, "reservado": reservado, "disponivel": disponivel}
        except Exception:
            pass
        return None

    def consultar_estoque(self, nome_produto: str = "", codigo_produto: str = ""):
        """Busca produtos e retorna estoque real via PosicaoEstoque."""
        termo = nome_produto or codigo_produto
        todos = self._listar_todos_produtos()
        resultado = []
        for p in todos:
            desc = p.get("descricao", "")
            cod = p.get("codigo", "")
            if termo and termo.lower() not in desc.lower() and termo.lower() not in cod.lower():
                continue
            # Busca saldo real
            cod_omie = p.get("codigo_produto", 0)
            posicao = self._posicao_estoque(cod_omie)
            if posicao:
                estoque_fisico = posicao["fisico"]
                estoque_disp = posicao["disponivel"]
                estoque_res = posicao["reservado"]
            else:
                # Fallback para o campo da listagem
                estoque_fisico = p.get("quantidade_estoque", 0)
                estoque_disp = estoque_fisico
                estoque_res = 0
            resultado.append({
                "codigo": cod,
                "descricao": desc,
                "unidade": p.get("unidade", ""),
                "estoque_fisico": estoque_fisico,
                "estoque_disponivel": estoque_disp,
                "estoque_reservado": estoque_res,
                "estoque_minimo": p.get("estoque_minimo", 0),
                "_empresa": self.empresa,
            })
        return {"produtos": resultado, "total": len(resultado)}

    def consultar_cliente(self, nome_cliente: str):
        return self._call("geral/clientes", "ListarClientes", {
            "pagina": 1, "registros_por_pagina": 10, "apenas_importado_api": "N",
            "clientesFiltro": {"razao_social": nome_cliente}
        })

    def buscar_fornecedor(self, nome: str):
        r = self._call("geral/clientes", "ListarClientes", {
            "pagina": 1, "registros_por_pagina": 20, "apenas_importado_api": "N",
            "clientesFiltro": {"razao_social": nome}
        })
        return [
            {"codigo": c["codigo_cliente_omie"], "nome": c.get("razao_social", ""), "fantasia": c.get("nome_fantasia", "")}
            for c in r.get("clientes_cadastro", [])
        ]

    def listar_categorias_despesa(self):
        path = _cache_path(self.empresa, "categorias")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        r = self._call("geral/categorias", "ListarCategorias", {"pagina": 1, "registros_por_pagina": 200})
        cats = r.get("categoria_cadastro", [])
        if not cats:
            return []
        resultado = [
            {"codigo": c["codigo"], "descricao": c["descricao"]}
            for c in cats
            if str(c.get("codigo", "")).startswith("2") and "<" not in c.get("descricao", "")
        ]
        _salvar_json(path, resultado)
        return resultado

    def listar_contas_correntes(self):
        r = self._call("geral/contacorrente", "ListarContasCorrentes", {"pagina": 1, "registros_por_pagina": 50})
        return [
            {"codigo": c["nCodCC"], "descricao": c.get("descricao", ""), "banco": c.get("codigo_banco", "")}
            for c in r.get("ListarContasCorrentes", [])
            if c.get("bloqueado") != "S"
        ]

    def baixar_pagamento(self, codigo_lancamento: int, codigo_conta_corrente: int, valor: float, data_pagamento: str):
        return self._call("financas/contapagar", "LancarPagamento", {
            "codigo_lancamento": codigo_lancamento,
            "codigo_conta_corrente": codigo_conta_corrente,
            "data": data_pagamento,
            "valor": valor,
        })

    def lancar_conta_pagar(self, codigo_fornecedor, valor, data_vencimento, data_previsao,
                           codigo_categoria, numero_documento="", observacao="", codigo_barras=""):
        payload = {
            "codigo_lancamento_integracao": f"ASSIST_{int(time.time())}",
            "codigo_cliente_fornecedor": codigo_fornecedor,
            "data_vencimento": data_vencimento,
            "data_previsao": data_previsao,
            "valor_documento": valor,
            "codigo_categoria": codigo_categoria,
            "numero_documento": numero_documento,
            "observacao": observacao,
            "codigo_tipo_documento": "BOL",
        }
        if codigo_barras:
            payload["codigo_barras_ficha_compensacao"] = codigo_barras
        return self._call("financas/contapagar", "IncluirContaPagar", payload)

    def anexar_arquivo(self, tabela: str, codigo_omie: int, nome_arquivo: str, conteudo_bytes: bytes):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(nome_arquivo, conteudo_bytes)
        zip_bytes = zip_buffer.getvalue()
        b64 = base64.b64encode(zip_bytes).decode("utf-8")
        md5 = hashlib.md5(b64.encode("utf-8")).hexdigest()
        return self._call("geral/anexo", "IncluirAnexo", {
            "cTabela": tabela, "nId": codigo_omie,
            "cNomeArquivo": nome_arquivo, "cArquivo": b64, "cMd5": md5,
        })

    def resumo_financeiro(self):
        return {
            "empresa": self.empresa,
            "contas_receber": self.listar_contas_receber(30, "EMABERTO"),
            "contas_atrasadas": self.listar_contas_receber(0, "ATRASADO"),
            "contas_pagar": self.listar_contas_pagar(30, "EMABERTO"),
        }


# ── Helpers consolidados ─────────────────────────────────────────────────────

def get_api(empresa: str) -> OmieAPI:
    return OmieAPI(empresa)

def consolidar_contas_receber(dias=30, status="EMABERTO"):
    todas = []
    for emp in EMPRESAS:
        r = OmieAPI(emp).listar_contas_receber(dias, status)
        todas.extend(r.get("conta_receber_cadastro", []))
    return {"conta_receber_cadastro": todas, "total_de_registros": len(todas)}

def consolidar_contas_pagar(dias=30, status="EMABERTO"):
    todas = []
    for emp in EMPRESAS:
        r = OmieAPI(emp).listar_contas_pagar(dias, status)
        todas.extend(r.get("conta_pagar_cadastro", []))
    return {"conta_pagar_cadastro": todas, "total_de_registros": len(todas)}

def consolidar_pedidos(dias=30):
    todos = []
    for emp in EMPRESAS:
        r = OmieAPI(emp).listar_pedidos_venda(dias)
        todos.extend(r.get("pedido_venda_produto", []))
    return {"pedido_venda_produto": todos, "total_de_registros": len(todos)}

def consolidar_estoque(nome_produto="", codigo_produto=""):
    todos = []
    for emp in EMPRESAS:
        r = OmieAPI(emp).consultar_estoque(nome_produto, codigo_produto)
        todos.extend(r.get("produtos", []))
    return {"produtos": todos, "total": len(todos)}

def consolidar_resumo():
    result = {}
    for emp in EMPRESAS:
        result[emp] = OmieAPI(emp).resumo_financeiro()
    return result
