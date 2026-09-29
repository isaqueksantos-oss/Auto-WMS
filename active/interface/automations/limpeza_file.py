import os
import re
from pathlib import Path
import time
import pandas as pd
from collections import Counter
import unicodedata
import json
import pyarrow as pa
import pyarrow.parquet as pq
from functools import lru_cache


# Caminho para o arquivo JSON com tipos das colunas
TIPOS_JSON_PATH = Path("active/interface/utils/tipos_colunas.json")


logger = print  # função de log externa (pode ser substituída)


def set_logger(log_fn):
    """Define a função de logging customizada."""
    global logger
    logger = log_fn


def carregar_tipos_json(caminho: Path = TIPOS_JSON_PATH) -> dict:
    """
    Carrega mapeamento de tipos de colunas do arquivo JSON.
    
    Formato esperado do JSON:
    {
        "nome_coluna_normalizado": "date",
        "outra_coluna": "int",
        "valor_total": "float"
    }
    
    Returns:
        dict: Mapeamento {nome_coluna: tipo}
    """
    if not caminho.exists():
        logger(f"[AVISO] Arquivo de tipos não encontrado: {caminho}")
        logger("[INFO] Todas as colunas serão tratadas como string")
        return {}
    
    try:
        with open(caminho, encoding="utf-8") as f:
            tipos = json.load(f)
        logger(f"[OK] {len(tipos)} tipos de colunas carregados do JSON")
        return tipos
    except json.JSONDecodeError as e:
        logger(f"[ERRO] JSON inválido em {caminho}: {e}")
        return {}
    except Exception as e:
        logger(f"[ERRO] Falha ao carregar tipos: {e}")
        return {}


def aguardar_arquivo_estavel(path, timeout=60, intervalo=2):
    logger("[INFO] Aguardando arquivo finalizar escrita...")

    tempo = 0
    tamanho_anterior = -1

    while tempo < timeout:
        tamanho_atual = os.path.getsize(path)

        if tamanho_atual == tamanho_anterior:
            logger(f"[OK] Arquivo estável com {tamanho_atual} bytes")
            return

        tamanho_anterior = tamanho_atual
        time.sleep(intervalo)
        tempo += intervalo

    raise TimeoutError("Arquivo não estabilizou (ainda está sendo escrito)")


def detectar_separador(lines: list) -> str:
    """
    Detecta automaticamente o separador usado no arquivo.
    
    Testa: TAB, PIPE, SEMICOLON, COMMA
    Retorna o separador mais frequente em linhas de dados.
    """
    if not lines:
        return "\t"  # Padrão: TAB
    
    separadores_candidatos = {
        "TAB": "\t",
        "PIPE": "|",
        "SEMICOLON": ";",
        "COMMA": ","
    }
    
    contagem = {sep: 0 for sep in separadores_candidatos}
    
    # Analisar primeiras 100 linhas não-vazias
    for line in lines[:100]:
        if not line.strip():
            continue
        for nome, sep in separadores_candidatos.items():
            contagem[nome] += line.count(sep)
    
    # Retornar separador mais frequente
    sep_detectado = max(contagem, key=contagem.get)
    logger(f"[INFO] Separador detectado: {sep_detectado} (TAB={contagem['TAB']}, PIPE={contagem['PIPE']}, SEMICOLON={contagem['SEMICOLON']}, COMMA={contagem['COMMA']})")
    
    return separadores_candidatos[sep_detectado]


def empty_ratio(cols):
    """Calcula razão de colunas vazias."""
    empty = sum(1 for c in cols if not c or str(c).strip() == "")
    return empty / len(cols) if cols else 0


def is_effectively_blank_row(line: str, sep: str) -> bool:
    """
    Detecta linhas que parecem vazias mas na verdade são compostas
    apenas por colunas vazias/separadores do SAP.
    """
    if not line.strip():
        return True

    cols = split_cols(line, sep)

    if not cols:
        return True

    # 90% ou mais das colunas vazias = linha inútil do SAP
    return empty_ratio(cols) >= 0.9


def text_ratio(cols):
    """Calcula razão de colunas com texto."""
    text = sum(1 for c in cols if re.search(r"[A-Za-z]", c))
    return text / len(cols) if cols else 0


def numeric_ratio(cols):
    """Calcula razão de colunas com números."""
    num = sum(1 for c in cols if re.search(r"\d", c))
    return num / len(cols) if cols else 0


def is_sap_subtotal_hidden(line: str, sep: str) -> bool:
    """
    Detecta subtotais SAP que NÃO possuem '*'
    baseado na assinatura estrutural da linha.
    """
    cols = split_cols(line, sep)

    if len(cols) < 3:
        return False

    tr = text_ratio(cols)
    nr = numeric_ratio(cols)
    er = empty_ratio(cols)

    # Assinatura universal de subtotal SAP
    if tr < 0.2 and nr > 0.6 and er > 0.4:
        return True

    return False


def is_sap_subtotal_line(line: str, sep: str) -> bool:
    """
    Detecta linhas de subtotal do SAP iniciadas por '*'.
    """
    if not line.strip():
        return False

    cols = split_cols(line, sep)
    if not cols:
        return False

    primeira = cols[0].strip()
    return primeira.startswith("*")


def has_separator(line: str, sep: str) -> bool:
    return sep in line


def is_separator(line, sep="|"):
    """Verifica se a linha é um separador (linha de formatação)."""
    if sep == "|":
        return bool(re.fullmatch(r"[|\-\=\s]+", line))
    # Para outros separadores, detecta linhas com muitos hífen
    return bool(re.fullmatch(r"[\-\=\s]+", line)) or line.count("-") > 10


def split_cols(line, sep="\t"):
    """Divide uma linha em colunas usando o separador detectado."""
    if sep == "|":
        return [c.strip() for c in line.strip("|").split(sep)]
    else:
        return [c.strip() for c in line.strip().split(sep)]

@lru_cache(maxsize=None)
def normalizar_nome_coluna_bq(nome: str) -> str:
    """
    Normaliza nome de coluna para padrão BigQuery.
    
    Regras:
    - Remove acentos
    - Converte para lowercase
    - Substitui caracteres especiais por _
    - Remove _ duplicados
    - Prefixa com _ se começar com número
    """
    # Remove acentos
    nome = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")

    # Lowercase
    nome = nome.lower()

    # Substitui qualquer coisa que não seja letra/número por _
    nome = re.sub(r"[^a-z0-9]", "_", nome)

    # Remove múltiplos _
    nome = re.sub(r"_+", "_", nome)

    # Remove _ do início/fim
    nome = nome.strip("_")

    # Se começar com número, prefixa _
    if re.match(r"^\d", nome):
        nome = "_" + nome

    return nome


def read_sap_file(path):
    """Lê arquivo SAP com detecção automática de encoding."""
    encodings = ["utf-8", "latin-1", "cp1252", "iso-8859-1"]

    for enc in encodings:
        try:
            with open(path, encoding=enc) as f:
                lines = f.readlines()
                logger(f"[INFO] Arquivo lido com encoding: {enc}")
                return lines
        except UnicodeDecodeError:
            logger(f"[AVISO] Encoding {enc} falhou, tentando próximo...")
            continue
        except Exception as e:
            logger(f"[AVISO] Erro ao ler com {enc}: {e}")
            continue

    raise UnicodeDecodeError("Não foi possível identificar o encoding do arquivo SAP.")


def detectar_cabecalho_por_primeiro_dado(lines, sep="\t"):
    """
    Fallback para relatórios pequenos.
    Encontra a primeira linha de dados e assume que o cabeçalho
    é a linha válida imediatamente anterior.
    """
    last_candidate = None

    for i, line in enumerate(lines):
        if (
            not line.strip()
            or not has_separator(line, sep)
            or is_separator(line, sep)
            or is_effectively_blank_row(line, sep)
            or is_sap_subtotal_line(line, sep)
            or is_sap_subtotal_hidden(line, sep)
        ):
            continue

        cols = split_cols(line, sep)

        if len(cols) < 2:
            continue

        nr = numeric_ratio(cols)

        # Linha claramente de dados
        if nr >= 0.5:
            if last_candidate:
                logger(f"[FALLBACK] Cabeçalho identificado na linha {last_candidate['index']}")
                return last_candidate["line"], last_candidate["cols"]
            break

        # Linha textual estruturada → possível cabeçalho
        tr = text_ratio(cols)
        if tr >= 0.5:
            last_candidate = {
                "index": i,
                "line": line.strip(),
                "cols": cols
            }

    raise ValueError("Fallback falhou ao identificar o cabeçalho.")


def aplicar_tipos_colunas(df: pd.DataFrame, tipos_mapa: dict) -> pd.DataFrame:
    """
    Aplica tipos às colunas do DataFrame baseado no mapeamento JSON.
    
    Tipos suportados:
    - "string" ou "str": Mantém como string
    - "int": Inteiro (converte formato SAP: 1.234 → 1234)
    - "float": Float (converte formato SAP: 1.234,56 → 1234.56)
    - "date": Data (converte dd.mm.yyyy → datetime)
    - "time": Hora (converte HH:MM:SS → time)
    - "datetime": Data e hora
    
    Args:
        df: DataFrame com dados
        tipos_mapa: Dicionário {nome_coluna_normalizado: tipo}
    
    Returns:
        DataFrame com tipos aplicados
    """
    logger("[INFO] Aplicando tipos às colunas...")
    
    colunas_mapeadas = 0
    colunas_nao_mapeadas = 0

    def _normalizar_numero_str(serie: pd.Series) -> pd.Series:
        """
        Normaliza strings numéricas:
        - Remove separador de milhar (.)
        - Converte vírgula decimal para ponto
        - Move sinal negativo do final para o início (ex: 352,44- -> -352.44)
        """
        s = serie.astype(str).str.strip()
        neg_trailing = s.str.endswith("-")
        s = s.str.rstrip("-")
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        s = s.where(~neg_trailing | s.str.startswith("-"), "-" + s)
        return s
    
    for col in df.columns:
        # Pular colunas de metadados
        if col in ["dt_ingestao", "timestamp_ingestao"]:
            continue
        
        # Verificar se coluna existe no mapeamento
        if col not in tipos_mapa:
            # Coluna não mapeada = string por padrão (sem remover zeros)
            # Preservar NULLs antes de converter para string
            mask_null = df[col].isna()
            df[col] = df[col].astype(str)
            df[col] = df[col].replace('', pd.NA)
            # Restaurar NULLs originais (evita "nan" como string)
            df[col] = df[col].mask(mask_null, pd.NA)
            colunas_nao_mapeadas += 1
            logger(f"  ⚠ {col} → string (não mapeada)")
            continue
        
        tipo = tipos_mapa[col].lower()
        colunas_mapeadas += 1
        
        try:
            if tipo in ["string", "str"]:
                # Apenas para STRING: remover zeros à esquerda
                # Preservar NULLs antes de converter para string
                mask_null = df[col].isna()
                df[col] = df[col].astype(str).str.lstrip('0')
                df[col] = df[col].replace('', pd.NA)
                # Restaurar NULLs originais (evita "nan" como string)
                df[col] = df[col].mask(mask_null, pd.NA)
                logger(f"  ✓ {col} → string (zeros à esquerda removidos)")
            
            elif tipo == "int":
                # Padroniza formato SAP
                limpo = _normalizar_numero_str(df[col])

                # Converte para número (float primeiro)
                numeros = pd.to_numeric(limpo, errors="coerce")

                # Mantém apenas valores inteiros reais (descarta decimais ≠ .00)
                numeros_validos = numeros.where(
                    numeros.isna() | (numeros % 1 == 0)
                )

                # Converte para inteiro nullable
                df[col] = numeros_validos.astype("Int64")

                logger(f"  ✓ {col} → int (decimais != .00 descartados)")
            
            elif tipo == "float":
                # Converter formato SAP: 1.234,56 → 1234.56
                limpo = _normalizar_numero_str(df[col])
                df[col] = pd.to_numeric(limpo, errors="coerce")
                logger(f"  ✓ {col} → float")
            
            elif tipo == "date":
                # Converter dd.mm.yyyy → datetime
                df[col] = pd.to_datetime(
                    df[col],
                    format="%d.%m.%Y",
                    errors="coerce"
                )
                logger(f"  ✓ {col} → date")
            
            elif tipo == "time":
                # Converter HH:MM:SS → timedelta (para compatibilidade com PyArrow time64)
                df[col] = pd.to_timedelta(df[col], errors="coerce")
                logger(f"  ✓ {col} → time (timedelta)")
            
            elif tipo == "datetime":
                # Converter para datetime (formato a definir)
                df[col] = pd.to_datetime(df[col], errors="coerce")
                logger(f"  ✓ {col} → datetime")
            
            else:
                # Tipo desconhecido = string (sem remover zeros, apenas conversão)
                mask_null = df[col].isna()
                df[col] = df[col].astype(str)
                df[col] = df[col].replace('', pd.NA)
                df[col] = df[col].mask(mask_null, pd.NA)
                logger(f"  ⚠ {col} → string (tipo '{tipo}' não reconhecido)")
        
        except Exception as e:
            logger(f"  ✗ {col} → string (erro ao aplicar tipo '{tipo}': {e})")
            mask_null = df[col].isna()
            df[col] = df[col].astype(str)
            df[col] = df[col].replace('', pd.NA)
            df[col] = df[col].mask(mask_null, pd.NA)
    
    logger(f"[OK] Tipos aplicados: {colunas_mapeadas} mapeadas, {colunas_nao_mapeadas} não mapeadas")
    
    return df


def limpar_arquivo_sap(
    caminho_entrada: str,
    exportar_para_bq: bool = True,
    caminho_tipos_json: Path = TIPOS_JSON_PATH
) -> tuple[str, str]:
    """
    Limpa arquivo SAP extraído em .txt e retorna arquivo .xlsx no mesmo diretório.
    
    Processo:
    1. Lê arquivo .txt com detecção automática de encoding
    2. Detecta separador (TAB, PIPE, SEMICOLON, etc)
    3. Identifica cabeçalho pelo padrão mais frequente
    4. Extrai dados filtrando separadores
    5. Carrega tipos do JSON
    6. Aplica tipos às colunas (colunas não mapeadas = string)
    7. Exporta para .xlsx e .parquet
    
    Args:
        caminho_entrada: Caminho do arquivo .txt
        exportar_para_bq: Se True, converte datas para string YYYY-MM-DD
        caminho_tipos_json: Caminho do arquivo JSON com tipos
    
    Returns:
        tuple[str, str]: (caminho_xlsx, caminho_parquet)
    
    Raises:
        FileNotFoundError: Se arquivo de entrada não existir
        ValueError: Se não conseguir identificar o cabeçalho
    """
    try:
        entrada = Path(caminho_entrada)
        
        if not entrada.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho_entrada}")
        
        aguardar_arquivo_estavel(str(entrada))
        
        if entrada.suffix.lower() != ".txt":
            raise ValueError(f"Arquivo deve ser .txt, recebido: {entrada.suffix}")
        
        logger(f"[INFO] Lendo arquivo SAP: {entrada.name}")
        
        # --- 1. LER ARQUIVO ---
        lines = [l.rstrip("\n") for l in read_sap_file(str(entrada))]
        logger(f"[INFO] {len(lines)} linhas lidas")
        
        # --- 2. DETECTAR SEPARADOR ---
        sep = detectar_separador(lines)
        logger(f"[INFO] Usando separador: {repr(sep)}")
        
        # --- 3. IDENTIFICAR CABEÇALHO ---
        logger("[INFO] Identificando cabeçalho...")
        candidates = []

        for i, line in enumerate(lines):
            if (
                not line.strip()
                or not has_separator(line, sep)
                or is_separator(line, sep)
                or is_effectively_blank_row(line, sep)
                or is_sap_subtotal_line(line, sep)
                or is_sap_subtotal_hidden(line, sep)
            ):
                continue

            cols = split_cols(line, sep)

            if len(cols) < 2:
                continue

            tr = text_ratio(cols)
            nr = numeric_ratio(cols)

            # Heurística forte de título
            if (
                tr >= 0.6
                and nr <= 0.3
                and len(cols) >= 6
                and len(line.strip()) > 20
            ):
                candidates.append({
                    "index": i,
                    "line": line.strip(),
                    "cols": cols
                })

        if not candidates:
            logger("[WARN] Heurística principal falhou. Tentando fallback...")
            try:
                header_line, header_cols = detectar_cabecalho_por_primeiro_dado(lines, sep)
            except ValueError as e:
                logger(f"[ERRO] {e}")
                raise
        else:
            counter = Counter(c["line"] for c in candidates)
            header_line = counter.most_common(1)[0][0]
            header_cols = split_cols(header_line, sep)

        expected_cols = len(header_cols)
        
        # --- NORMALIZAR NOMES DE COLUNA PARA BIGQUERY ---
        logger("[INFO] Normalizando nomes de colunas para BigQuery...")

        original_cols = header_cols.copy()
        header_cols = [normalizar_nome_coluna_bq(c) for c in header_cols]

        for o, n in zip(original_cols, header_cols):
            if o != n:
                logger(f"  {o}  →  {n}")

        logger(f"[OK] Cabeçalho identificado: {expected_cols} colunas")
        logger(f"[INFO] Colunas: {', '.join(header_cols[:5])}{'...' if len(header_cols) > 5 else ''}")
        
        # --- 4. EXTRAIR DADOS ---
        logger("[INFO] Extraindo dados...")
        data_rows = []
        started = False
        linha_numero = 0
        erro_count = 0

        for linha_numero, line in enumerate(lines, 1):
            try:
                if (
                    not line.strip()
                    or not has_separator(line, sep)
                    or is_separator(line, sep)
                    or is_effectively_blank_row(line, sep)
                    or is_sap_subtotal_line(line, sep)
                    or is_sap_subtotal_hidden(line, sep)
                ):
                    continue

                clean = line.strip()

                cols_raw = split_cols(clean, sep)

                # Verificar se é o cabeçalho
                if [normalizar_nome_coluna_bq(c) for c in cols_raw] == header_cols:
                    started = True
                    logger(f"[INFO] Cabeçalho encontrado na linha {linha_numero}")
                    continue

                if not started:
                    continue

                cols = split_cols(clean, sep)

                # Ajusta tamanho da linha ao cabeçalho
                if len(cols) < expected_cols:
                    cols.extend([None] * (expected_cols - len(cols)))
                elif len(cols) > expected_cols:
                    cols = cols[:expected_cols]

                data_rows.append(cols)
                
            except Exception as e:
                erro_count += 1
                if erro_count <= 5:
                    logger(f"[AVISO] Erro ao processar linha {linha_numero}: {e}")
                if erro_count == 6:
                    logger(f"[AVISO] ... (suprimindo erros adicionais)")
                continue

        logger(f"[OK] {len(data_rows)} linhas de dados extraídas (linha {linha_numero})")
        if erro_count > 0:
            logger(f"[AVISO] Total de {erro_count} linhas com erro durante extração")
        
        if len(data_rows) == 0:
            raise ValueError("Nenhuma linha de dados foi extraída!")

        # --- 5. CRIAR DATAFRAME ---
        logger("[INFO] Criando DataFrame...")
        try:
            agora = pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None)
            df = pd.DataFrame(data_rows, columns=header_cols)
            df["dt_ingestao"] = agora.date()
            df["timestamp_ingestao"] = agora              # Timestamp completo
            df.replace("", pd.NA, inplace=True)
            df.reset_index(drop=True, inplace=True)
            df.dropna(how="all", inplace=True)
            df.reset_index(drop=True, inplace=True)
            logger(f"[INFO] Linhas totalmente vazias removidas: {len(df)} restantes")

            logger(f"[OK] DataFrame criado: {len(df)} linhas × {len(header_cols)} colunas")
        except Exception as e:
            logger(f"[ERRO] Falha ao criar DataFrame: {e}")
            raise

        # --- 6. CARREGAR TIPOS DO JSON ---
        tipos_mapa = carregar_tipos_json(caminho_tipos_json)
        
        # --- 7. APLICAR TIPOS ÀS COLUNAS ---
        df = aplicar_tipos_colunas(df, tipos_mapa)

        # --- 8. EXPORTAR ---
        logger("[INFO] Exportando para Excel...")
        
        df_export = df.copy()

        # Converter datas para string no formato YYYY-MM-DD se BigQuery
        if exportar_para_bq:
            for col in df_export.columns:
                if pd.api.types.is_datetime64_any_dtype(df_export[col]):
                    if col == "timestamp_ingestao":
                        # Timestamp completo com hora
                        df_export[col] = df_export[col].dt.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        # Apenas data
                        df_export[col] = df_export[col].dt.strftime("%Y-%m-%d")

        # Salvar em mesmo diretório com extensão .xlsx
        caminho_saida = entrada.with_suffix(".xlsx")
        #df_export.to_excel(str(caminho_saida), index=False)
        logger(f"[OK] Arquivo Excel salvo: {caminho_saida.name}")

        # --- PREPARAR DATAFRAME E SCHEMA PARA PARQUET ---
        logger("[INFO] Preparando parquet com schema explícito...")
        df_parquet = df.copy()
        
        # PASSO 1: Converter todos objetos incompatíveis com PyArrow ANTES de construir schema
        logger("[INFO] Convertendo tipos incompatíveis com PyArrow...")
        
        import datetime
        
        for col in df_parquet.columns:
            # Detectar colunas com datetime.date ou datetime.time objects
            if df_parquet[col].dtype == 'object':
                # Pegar primeira amostra não-nula
                sample = df_parquet[col].dropna().head(1)
                if len(sample) > 0:
                    first_val = sample.iloc[0]
                    
                    # datetime.date object (mas não datetime.datetime)
                    if isinstance(first_val, datetime.date) and not isinstance(first_val, datetime.datetime):
                        logger(f"  [DATE OBJECT] {col} contém datetime.date objects - convertendo para datetime64")
                        df_parquet[col] = pd.to_datetime(df_parquet[col])
                    
                    # datetime.time object → converter para timedelta (microssegundos desde meia-noite)
                    elif isinstance(first_val, datetime.time):
                        logger(f"  [TIME OBJECT] {col} contém datetime.time objects - convertendo para time64")
                        df_parquet[col] = df_parquet[col].apply(
                            lambda x: pd.Timedelta(
                                hours=x.hour, 
                                minutes=x.minute, 
                                seconds=x.second, 
                                microseconds=x.microsecond
                            ) if isinstance(x, datetime.time) else pd.NaT
                        )
        
        # PASSO 2: Construir schema PyArrow explícito
        schema_fields = []
        
        for col in df_parquet.columns:            
            # Converter datetime para formato adequado
            if pd.api.types.is_datetime64_any_dtype(df_parquet[col]):
                if col == "timestamp_ingestao":
                    # TIMESTAMP: manter como datetime64[us] → timestamp[us]
                    df_parquet[col] = df_parquet[col].astype("datetime64[us]")
                    schema_fields.append(pa.field(col, pa.timestamp('us')))
                else:
                    # DATE: converter para date32 (dias desde epoch)
                    # Já está em datetime64[ns] após conversão acima
                    schema_fields.append(pa.field(col, pa.date32()))
            
            # Detectar colunas timedelta (convertidas de TIME)
            elif pd.api.types.is_timedelta64_dtype(df_parquet[col]):
                # TIME: converter timedelta para int64 (microssegundos desde meia-noite)
                # PyArrow time64 espera inteiros em microssegundos
                df_parquet[col] = df_parquet[col].dt.total_seconds() * 1_000_000
                df_parquet[col] = df_parquet[col].astype('Int64')  # Nullable integer
                schema_fields.append(pa.field(col, pa.time64('us')))
                logger(f"  [TIME64] {col} convertido para microssegundos (BigQuery TIME)")
            
            # CORREÇÃO CRÍTICA: Forçar colunas tipadas como date/datetime no JSON
            elif col in tipos_mapa:
                tipo = tipos_mapa[col].lower()
                
                if tipo == "date":
                    # Converter para datetime e definir schema como DATE32
                    df_parquet[col] = pd.to_datetime(df_parquet[col], errors="coerce")
                    schema_fields.append(pa.field(col, pa.date32()))
                    
                    if df_parquet[col].isna().all():
                        logger(f"  [FIX] {col} está vazia mas tipada como 'date' - schema forçado para DATE32")
                
                elif tipo == "datetime":
                    # Converter para datetime e definir schema como TIMESTAMP
                    df_parquet[col] = pd.to_datetime(df_parquet[col], errors="coerce")
                    schema_fields.append(pa.field(col, pa.timestamp('us')))
                    
                    if df_parquet[col].isna().all():
                        logger(f"  [FIX] {col} está vazia mas tipada como 'datetime' - schema forçado para TIMESTAMP")
                
                elif tipo == "time":
                    # TIME: converter para int64 microssegundos se ainda não foi
                    if not pd.api.types.is_timedelta64_dtype(df_parquet[col]):
                        # Parse string HH:MM:SS para timedelta primeiro
                        df_parquet[col] = pd.to_timedelta(df_parquet[col], errors="coerce")
                    
                    # Converter timedelta para microssegundos (int64)
                    df_parquet[col] = df_parquet[col].dt.total_seconds() * 1_000_000
                    df_parquet[col] = df_parquet[col].astype('Int64')
                    schema_fields.append(pa.field(col, pa.time64('us')))
                    logger(f"  [TIME64] {col} convertido para microssegundos (BigQuery TIME)")
                
                elif tipo == "int":
                    schema_fields.append(pa.field(col, pa.int64()))
                
                elif tipo == "float":
                    schema_fields.append(pa.field(col, pa.float64()))
                
                else:
                    # String ou tipo desconhecido
                    schema_fields.append(pa.field(col, pa.string()))
            
            # Colunas sem mapeamento
            else:
                # Inferir tipo baseado no dtype atual
                if pd.api.types.is_integer_dtype(df_parquet[col]):
                    schema_fields.append(pa.field(col, pa.int64()))
                elif pd.api.types.is_float_dtype(df_parquet[col]):
                    schema_fields.append(pa.field(col, pa.float64()))
                else:
                    schema_fields.append(pa.field(col, pa.string()))

        # Criar schema PyArrow
        schema = pa.schema(schema_fields)
        
        logger("[INFO] Schema PyArrow criado:")
        for field in schema:
            logger(f"  {field.name}: {field.type}")

        # Criar pasta parquet e salvar com schema explícito
        parquet_dir = entrada.parent / "parquet"
        parquet_dir.mkdir(exist_ok=True)
        caminho_parquet = parquet_dir / caminho_saida.name.replace(".xlsx", ".parquet")
        
        # Converter DataFrame para PyArrow Table com schema explícito
        table = pa.Table.from_pandas(df_parquet, schema=schema, preserve_index=False)
        
        # Salvar parquet
        pq.write_table(table, str(caminho_parquet))

        logger(f"[OK] Arquivo salvo: {caminho_saida.name} e {caminho_parquet.name}")
        logger(f"[INFO] Resumo: {len(df)} linhas × {len(header_cols)} colunas")

        return str(caminho_saida), str(caminho_parquet)

    except Exception as e:
        logger(f"[ERRO] Falha ao limpar arquivo: {e}")
        raise


# ===================== EXEMPLO DE USO =====================
if __name__ == "__main__":
    # Exemplo: python limpeza_sap_com_json.py
    try:
        arquivo_entrada = "active/interface/extracao_sap.txt"
        arquivo_saida, arquivo_parquet = limpar_arquivo_sap(arquivo_entrada, exportar_para_bq=True)
        print(f"\n✅ Arquivo limpo salvo em: {arquivo_saida} e {arquivo_parquet}")
    except Exception as e:
        print(f"\n❌ Erro: {e}")
