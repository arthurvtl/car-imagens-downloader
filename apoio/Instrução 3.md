# Instrução 3 — Prompt Completo de Implementação do Pipeline de Extração de Imagens

> Este documento é o blueprint completo de implementação. Tudo que está escrito aqui deve ser construído do zero, em Python, seguindo as boas práticas definidas nas Instruções 1 e 2.

---

## CONTEXTO DO PROJETO

**Nome:** IntegraCar  
**Instituição:** IFES Campus Serra  
**Parceiros:** FAPES, IDAF e outros órgãos do Estado do Espírito Santo  
**Objetivo geral:** Cadastramento e análise do CAR (Cadastro Ambiental Rural) no ES por meio de modelos de segmentação semântica de imagens de satélite.

**Objetivo desta automação:**  
Dado um arquivo CSV contendo coordenadas geográficas de imóveis rurais cadastrados no CAR-ES, baixar automaticamente, para cada imóvel, um par de imagens georreferenciadas que servirão como entrada para um modelo de segmentação semântica já existente:
1. A imagem de satélite bruta (raster sem classificação)
2. O mapa de uso do solo segmentado (raster com classes de cobertura por cor)

**Inspiração arquitetural:** BigEarthNet v2 Pipeline (TU Berlin) — metodologia de construção de datasets de sensoriamento remoto com pares de imagem bruta + mapa de referência, manifesto CSV com hashes de integridade, downloads idempotentes e artefatos versionados.

---

## ENTRADAS DO SISTEMA

### 1. Arquivo CSV de coordenadas
- **Nome:** `coordenadas_treino_amostra.csv`
- **Separador:** ponto e vírgula (`;`)
- **Encoding:** UTF-8
- **Colunas:**
  - `cod_imovel` — identificador único do imóvel no CAR (string, ex: `ES-3200136-AED7CD85F9FA458FBC0774E88DF33101`)
  - `x` — coordenada X em metros, sistema UTM (float, ex: `317411.43075053697`)
  - `y` — coordenada Y em metros, sistema UTM (float, ex: `7898046.959248656`)
- **Projeção das coordenadas:** EPSG:31984 (SIRGAS 2000 / UTM zona 24S)
- **Total de amostras no arquivo de exemplo:** 282 imóveis

### 2. Serviço WMS do GeoBases
- **Endpoint único:** `https://ide.geobases.es.gov.br/geoserver/ows`
- **Plataforma:** GeoNode 3.1.0 + GeoServer
- **Protocolo:** OGC WMS 1.1.1
- **Camada de satélite bruta:** typename a ser confirmado no QGIS (relacionado ao KOMPSAT 2019/2020)
- **Camada de uso do solo:** typename a ser confirmado no QGIS (relacionado ao IJSN Uso do Solo)
- **Ambas as camadas devem estar em EPSG:31984**

> **ATENÇÃO — pré-requisito obrigatório antes de rodar o pipeline:**  
> Antes de executar qualquer código, o typename exato de cada camada deve ser preenchido em `configuracoes.py`. Para descobrir os typenames:  
> 1. Abrir o QGIS  
> 2. Adicionar uma nova conexão WMS apontando para `https://ide.geobases.es.gov.br/geoserver/ows`  
> 3. Localizar as camadas KOMPSAT e Uso do Solo IJSN  
> 4. Verificar o nome técnico (typename) nos metadados de cada camada

### 3. Configurações do pipeline
- Arquivo `configuracoes.py` (descrito em detalhe na seção de implementação)

---

## SAÍDAS DO SISTEMA

### 1. Pares de imagens GeoTIFF por imóvel
Para cada linha do CSV de entrada, o pipeline gera dois arquivos:

```
saida/
├── ES-3200136-AED7CD85F9FA458FBC0774E88DF33101/
│   ├── satelite.tif       ← GeoTIFF 1024×1024 px, RGB, EPSG:31984, georreferenciado
│   └── uso_solo.tif       ← GeoTIFF 1024×1024 px, RGB, EPSG:31984, georreferenciado
├── ES-3201001-3619B00F98E3414696F757137739949C/
│   ├── satelite.tif
│   └── uso_solo.tif
...
```

**Especificações técnicas obrigatórias de cada GeoTIFF:**
- Largura: 1024 pixels
- Altura: 1024 pixels
- Número de bandas: 3 (R, G, B)
- Tipo de dado: uint8 (valores 0–255)
- CRS gravado no arquivo: EPSG:31984
- Transform afim gravado no arquivo: derivado do bounding box (origem em xmin, ymax; pixel size = buffer*2/1024 metros)
- Compressão: LZW (padrão rasterio para TIF)
- Driver: GTiff

### 2. Manifesto do dataset
- **Arquivo:** `artifacts/dataset_manifesto.csv`
- **Separador:** ponto e vírgula (`;`)
- **Atualizado a cada download bem-sucedido ou falho**
- **Colunas:**

```
cod_imovel;x;y;bbox_xmin;bbox_ymin;bbox_xmax;bbox_ymax;status_satelite;status_uso_solo;hash_sha256_satelite;hash_sha256_uso_solo;data_download
```

- `status_satelite` / `status_uso_solo`: valores possíveis: `ok`, `erro`, `pulado`
- `hash_sha256_*`: hash SHA256 do arquivo TIF gerado (vazio se erro)
- `data_download`: timestamp ISO 8601 (ex: `2026-03-02T14:30:00`)

### 3. Log de execução
- **Arquivo:** `logs/execucao.log`
- Registra início, fim, erros por imóvel e resumo final

---

## ESTRUTURA DE ARQUIVOS DO PROJETO

```
projeto-automacao/
│
├── configuracoes.py            ← ÚNICO lugar com parâmetros alteráveis
├── extrator.py                 ← script principal, ponto de entrada (python extrator.py)
│
├── utils/
│   ├── __init__.py
│   ├── wms.py                  ← funções de requisição e conversão WMS → GeoTIFF
│   ├── manifesto.py            ← leitura e escrita do CSV de manifesto
│   └── integridade.py          ← cálculo e verificação de hashes SHA256
│
├── saida/                      ← gerado automaticamente, NÃO versionar no Git
│   └── {cod_imovel}/
│       ├── satelite.tif
│       └── uso_solo.tif
│
├── artifacts/                  ← versionar no Git como referência do dataset
│   └── dataset_manifesto.csv
│
├── logs/                       ← gerado automaticamente, NÃO versionar no Git
│   └── execucao.log
│
├── coordenadas_treino_amostra.csv
├── requirements.txt
├── .gitignore
└── venv/
```

---

## DEPENDÊNCIAS — requirements.txt

```
pandas==2.2.3
requests==2.32.3
rasterio==1.4.3
numpy==2.2.3
tqdm==4.67.1
Pillow==11.1.0
```

> `Pillow` é usado só para decodificar a resposta binária do WMS antes de passar ao `rasterio`. `concurrent.futures` já vem embutido no Python (não precisa instalar).

Instalar com:
```bash
pip install -r requirements.txt
```

---

## .gitignore

```
venv/
saida/
logs/
__pycache__/
*.pyc
.env
```

---

## IMPLEMENTAÇÃO DETALHADA — ARQUIVO POR ARQUIVO

---

### `configuracoes.py`

Este é o único arquivo que o usuário precisará editar para adaptar o pipeline a uma base de dados diferente. Toda configuração deve estar aqui, nunca hardcoded nos outros módulos.

```python
# configuracoes.py
# Ponto central de configuração do pipeline IntegraCar.
# Edite este arquivo para adaptar a outras camadas, tamanhos ou bases de dados.

CONFIGURACOES = {
    # --- Fonte de dados ---
    "wms_url": "https://ide.geobases.es.gov.br/geoserver/ows",
    "wms_versao": "1.1.1",

    # Typenames das camadas no GeoBases — confirmar no QGIS antes de executar
    "camada_satelite": "geonode:PREENCHER_TYPENAME_KOMPSAT",
    "camada_uso_solo": "geonode:PREENCHER_TYPENAME_IJSN_USO_SOLO",

    # --- Sistema de referência ---
    "srid_wms": "EPSG:31984",       # SRS usado na requisição WMS
    "epsg_codigo": 31984,           # Código numérico para gravar no GeoTIFF com rasterio

    # --- Dimensões do recorte ---
    # buffer_metros define metade do lado do quadrado recortado ao redor do ponto central.
    # Com buffer=512 e 1024 pixels → resolução de 1m/pixel (compatível com KOMPSAT ~1m).
    "buffer_metros": 512,
    "largura_pixels": 1024,
    "altura_pixels": 1024,

    # --- Formato da requisição WMS ---
    "formato_wms": "image/tiff",    # Solicitar diretamente em TIFF ao GeoServer
    "transparente": "FALSE",

    # --- Saídas ---
    "pasta_saida": "saida",
    "pasta_artifacts": "artifacts",
    "pasta_logs": "logs",
    "nome_arquivo_satelite": "satelite.tif",
    "nome_arquivo_uso_solo": "uso_solo.tif",
    "nome_manifesto": "dataset_manifesto.csv",
    "nome_log": "execucao.log",

    # --- Entrada ---
    "arquivo_csv": "coordenadas_treino_amostra.csv",
    "separador_csv": ";",

    # --- Comportamento do pipeline ---
    "pular_se_existir": True,       # Se True, pula imóveis que já têm os dois TIFs no disco
    "workers_paralelos": 4,         # Número de downloads simultâneos (cuidado com rate limit)
    "timeout_requisicao": 60,       # Segundos de timeout por requisição WMS
    "tentativas_por_imagem": 3,     # Número de retentativas em caso de falha de rede
    "pausa_entre_tentativas": 5,    # Segundos de espera entre retentativas
}
```

---

### `utils/integridade.py`

```python
# utils/integridade.py
# Funções para verificar integridade de arquivos via hash SHA256.
# Inspirado na prática do BigEarthNet pipeline de rastrear hashes de cada arquivo gerado.

import hashlib
from pathlib import Path


def calcular_hash_sha256(caminho_arquivo: str | Path) -> str:
    """
    Calcula e retorna o hash SHA256 do conteúdo binário de um arquivo.
    Lê o arquivo em blocos para não carregar arquivos grandes inteiros na memória.
    """
    hash_sha256 = hashlib.sha256()
    with open(caminho_arquivo, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(8192), b""):
            hash_sha256.update(bloco)
    return hash_sha256.hexdigest()


def verificar_arquivo_integro(caminho_arquivo: str | Path, hash_esperado: str) -> bool:
    """
    Retorna True se o hash SHA256 do arquivo bate com o hash_esperado.
    Retorna False se o arquivo não existe ou se o hash diverge.
    """
    caminho = Path(caminho_arquivo)
    if not caminho.exists():
        return False
    return calcular_hash_sha256(caminho) == hash_esperado
```

---

### `utils/manifesto.py`

```python
# utils/manifesto.py
# Gerencia o arquivo CSV de manifesto do dataset.
# O manifesto registra cada imóvel processado com seu status, bbox, hashes e timestamp.
# Inspirado nos "tracked-artifacts" do BigEarthNet pipeline.

import csv
import os
from datetime import datetime
from pathlib import Path

COLUNAS_MANIFESTO = [
    "cod_imovel",
    "x",
    "y",
    "bbox_xmin",
    "bbox_ymin",
    "bbox_xmax",
    "bbox_ymax",
    "status_satelite",
    "status_uso_solo",
    "hash_sha256_satelite",
    "hash_sha256_uso_solo",
    "data_download",
]


def inicializar_manifesto(caminho_manifesto: str | Path) -> None:
    """
    Cria o arquivo de manifesto com o cabeçalho se ele ainda não existir.
    Não sobrescreve um manifesto existente.
    """
    caminho = Path(caminho_manifesto)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if not caminho.exists():
        with open(caminho, "w", newline="", encoding="utf-8") as arquivo_csv:
            writer = csv.DictWriter(arquivo_csv, fieldnames=COLUNAS_MANIFESTO, delimiter=";")
            writer.writeheader()


def carregar_imoveis_processados(caminho_manifesto: str | Path) -> set[str]:
    """
    Lê o manifesto e retorna um conjunto com os cod_imovel que já foram processados
    com status 'ok' em ambas as imagens. Usado para implementar downloads idempotentes.
    """
    caminho = Path(caminho_manifesto)
    imoveis_completos = set()
    if not caminho.exists():
        return imoveis_completos
    with open(caminho, "r", encoding="utf-8") as arquivo_csv:
        reader = csv.DictReader(arquivo_csv, delimiter=";")
        for linha in reader:
            if linha["status_satelite"] == "ok" and linha["status_uso_solo"] == "ok":
                imoveis_completos.add(linha["cod_imovel"])
    return imoveis_completos


def registrar_resultado(
    caminho_manifesto: str | Path,
    cod_imovel: str,
    x: float,
    y: float,
    bbox: tuple[float, float, float, float],
    status_satelite: str,
    status_uso_solo: str,
    hash_satelite: str = "",
    hash_uso_solo: str = "",
) -> None:
    """
    Acrescenta uma linha ao manifesto com o resultado do processamento de um imóvel.

    Parâmetros:
        bbox: tupla (xmin, ymin, xmax, ymax) em metros EPSG:31984
        status_*: 'ok', 'erro' ou 'pulado'
        hash_*: hash SHA256 do arquivo TIF (string vazia se não gerado)
    """
    caminho = Path(caminho_manifesto)
    linha = {
        "cod_imovel": cod_imovel,
        "x": x,
        "y": y,
        "bbox_xmin": bbox[0],
        "bbox_ymin": bbox[1],
        "bbox_xmax": bbox[2],
        "bbox_ymax": bbox[3],
        "status_satelite": status_satelite,
        "status_uso_solo": status_uso_solo,
        "hash_sha256_satelite": hash_satelite,
        "hash_sha256_uso_solo": hash_uso_solo,
        "data_download": datetime.now().isoformat(timespec="seconds"),
    }
    with open(caminho, "a", newline="", encoding="utf-8") as arquivo_csv:
        writer = csv.DictWriter(arquivo_csv, fieldnames=COLUNAS_MANIFESTO, delimiter=";")
        writer.writerow(linha)
```

---

### `utils/wms.py`

Este é o módulo mais importante. Encapsula toda a lógica de comunicação com o GeoServer e conversão dos dados recebidos em GeoTIFF georreferenciado.

```python
# utils/wms.py
# Funções de comunicação com o serviço WMS do GeoBases e conversão para GeoTIFF.
# Toda interação com a rede e o formato raster está isolada aqui.

import io
import time
import logging
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from PIL import Image

logger = logging.getLogger(__name__)


def calcular_bbox(x: float, y: float, buffer_metros: float) -> tuple[float, float, float, float]:
    """
    Calcula o bounding box quadrado ao redor de um ponto central.

    Parâmetros:
        x: coordenada X central em metros (EPSG:31984)
        y: coordenada Y central em metros (EPSG:31984)
        buffer_metros: metade do lado do quadrado em metros

    Retorna:
        Tupla (xmin, ymin, xmax, ymax) em metros
    """
    return (
        x - buffer_metros,
        y - buffer_metros,
        x + buffer_metros,
        y + buffer_metros,
    )


def montar_parametros_wms(
    camada: str,
    bbox: tuple[float, float, float, float],
    largura_pixels: int,
    altura_pixels: int,
    srid: str,
    wms_versao: str,
    formato: str,
    transparente: str,
) -> dict:
    """
    Monta o dicionário de parâmetros para uma requisição WMS GetMap.
    """
    xmin, ymin, xmax, ymax = bbox
    return {
        "SERVICE": "WMS",
        "VERSION": wms_versao,
        "REQUEST": "GetMap",
        "LAYERS": camada,
        "BBOX": f"{xmin},{ymin},{xmax},{ymax}",
        "WIDTH": largura_pixels,
        "HEIGHT": altura_pixels,
        "SRS": srid,
        "FORMAT": formato,
        "TRANSPARENT": transparente,
    }


def requisitar_imagem_wms(
    wms_url: str,
    parametros: dict,
    timeout: int,
    tentativas: int,
    pausa_entre_tentativas: int,
) -> bytes:
    """
    Realiza a requisição HTTP ao endpoint WMS e retorna o conteúdo binário da imagem.
    Em caso de falha de rede, retenta até `tentativas` vezes com pausa entre elas.

    Levanta:
        RuntimeError se todas as tentativas falharem.
    """
    for numero_tentativa in range(1, tentativas + 1):
        try:
            resposta = requests.get(wms_url, params=parametros, timeout=timeout)
            resposta.raise_for_status()

            # Verificar se o servidor retornou uma imagem (não uma mensagem de erro XML)
            tipo_conteudo = resposta.headers.get("Content-Type", "")
            if "xml" in tipo_conteudo or "html" in tipo_conteudo:
                raise RuntimeError(
                    f"Servidor retornou erro ao invés de imagem: {resposta.text[:300]}"
                )

            return resposta.content

        except (requests.RequestException, RuntimeError) as erro:
            logger.warning(
                f"Tentativa {numero_tentativa}/{tentativas} falhou: {erro}"
            )
            if numero_tentativa < tentativas:
                time.sleep(pausa_entre_tentativas)

    raise RuntimeError(f"Todas as {tentativas} tentativas falharam para a requisição WMS.")


def salvar_como_geotiff(
    conteudo_binario: bytes,
    caminho_saida: str | Path,
    bbox: tuple[float, float, float, float],
    largura_pixels: int,
    altura_pixels: int,
    epsg_codigo: int,
) -> None:
    """
    Converte o conteúdo binário recebido do WMS em um GeoTIFF georreferenciado.

    O GeoTIFF resultante contém:
    - 3 bandas RGB (uint8)
    - CRS definido pelo epsg_codigo
    - Transform afim derivado do bbox (posição geográfica real de cada pixel)

    Parâmetros:
        conteudo_binario: bytes retornados diretamente da resposta HTTP do WMS
        caminho_saida: caminho completo onde o arquivo .tif será gravado
        bbox: (xmin, ymin, xmax, ymax) em metros
        largura_pixels: largura da imagem em pixels (deve ser 1024)
        altura_pixels: altura da imagem em pixels (deve ser 1024)
        epsg_codigo: código numérico do CRS (ex: 31984)
    """
    caminho = Path(caminho_saida)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    # Decodificar o conteúdo binário em array numpy via Pillow
    imagem_pil = Image.open(io.BytesIO(conteudo_binario)).convert("RGB")
    array_imagem = np.array(imagem_pil)  # shape: (altura, largura, 3)

    # Calcular a transformação afim a partir do bbox
    # from_bounds(west, south, east, north, width, height)
    xmin, ymin, xmax, ymax = bbox
    transform_afim = from_bounds(xmin, ymin, xmax, ymax, largura_pixels, altura_pixels)

    crs = CRS.from_epsg(epsg_codigo)

    with rasterio.open(
        caminho,
        "w",
        driver="GTiff",
        height=altura_pixels,
        width=largura_pixels,
        count=3,           # 3 bandas: R, G, B
        dtype="uint8",
        crs=crs,
        transform=transform_afim,
        compress="lzw",
    ) as dataset_raster:
        # rasterio espera shape (bandas, altura, largura) — transpor o array numpy
        dataset_raster.write(array_imagem.transpose(2, 0, 1))


def baixar_imagem(
    wms_url: str,
    camada: str,
    bbox: tuple[float, float, float, float],
    caminho_saida: str | Path,
    largura_pixels: int,
    altura_pixels: int,
    srid: str,
    wms_versao: str,
    formato: str,
    transparente: str,
    epsg_codigo: int,
    timeout: int,
    tentativas: int,
    pausa_entre_tentativas: int,
) -> None:
    """
    Função de alto nível: realiza o download completo de uma imagem WMS e a salva
    como GeoTIFF georreferenciado. Combina montar_parametros_wms,
    requisitar_imagem_wms e salvar_como_geotiff.
    """
    parametros = montar_parametros_wms(
        camada=camada,
        bbox=bbox,
        largura_pixels=largura_pixels,
        altura_pixels=altura_pixels,
        srid=srid,
        wms_versao=wms_versao,
        formato=formato,
        transparente=transparente,
    )
    conteudo = requisitar_imagem_wms(
        wms_url=wms_url,
        parametros=parametros,
        timeout=timeout,
        tentativas=tentativas,
        pausa_entre_tentativas=pausa_entre_tentativas,
    )
    salvar_como_geotiff(
        conteudo_binario=conteudo,
        caminho_saida=caminho_saida,
        bbox=bbox,
        largura_pixels=largura_pixels,
        altura_pixels=altura_pixels,
        epsg_codigo=epsg_codigo,
    )
```

---

### `utils/__init__.py`

```python
# utils/__init__.py
# Arquivo vazio para tornar utils um pacote Python.
```

---

### `extrator.py`

Este é o ponto de entrada do pipeline. Orquestra a leitura do CSV, o download paralelo, o manifesto e o logging.

```python
# extrator.py
# Script principal do pipeline de extração de imagens IntegraCar.
# Execução: python extrator.py
#
# Fluxo:
# 1. Lê o CSV de coordenadas
# 2. Verifica quais imóveis já foram processados (idempotência)
# 3. Para cada imóvel pendente, baixa o par de imagens WMS como GeoTIFF 1024×1024
# 4. Registra o resultado (status + hash SHA256) no manifesto
# 5. Exibe progresso em tempo real e grava log de execução

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from configuracoes import CONFIGURACOES
from utils.integridade import calcular_hash_sha256
from utils.manifesto import (
    inicializar_manifesto,
    carregar_imoveis_processados,
    registrar_resultado,
)
from utils.wms import baixar_imagem, calcular_bbox


def configurar_logging(pasta_logs: str, nome_log: str) -> None:
    """Configura o sistema de logging para gravar em arquivo e exibir no terminal."""
    Path(pasta_logs).mkdir(parents=True, exist_ok=True)
    caminho_log = Path(pasta_logs) / nome_log

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(caminho_log, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def processar_imovel(
    cod_imovel: str,
    x: float,
    y: float,
    configuracoes: dict,
) -> dict:
    """
    Processa um único imóvel: calcula o bbox, baixa as duas imagens WMS e as
    salva como GeoTIFF georreferenciado. Retorna um dicionário com os resultados
    para ser gravado no manifesto.

    Parâmetros:
        cod_imovel: identificador único do imóvel (usado como nome da pasta)
        x, y: coordenadas centrais em metros (EPSG:31984)
        configuracoes: dicionário com todas as configurações do pipeline

    Retorna:
        Dicionário com campos do manifesto para este imóvel.
    """
    logger = logging.getLogger(__name__)

    cfg = configuracoes
    pasta_imovel = Path(cfg["pasta_saida"]) / cod_imovel
    caminho_satelite = pasta_imovel / cfg["nome_arquivo_satelite"]
    caminho_uso_solo = pasta_imovel / cfg["nome_arquivo_uso_solo"]

    bbox = calcular_bbox(x, y, cfg["buffer_metros"])

    resultado = {
        "cod_imovel": cod_imovel,
        "x": x,
        "y": y,
        "bbox": bbox,
        "status_satelite": "erro",
        "status_uso_solo": "erro",
        "hash_satelite": "",
        "hash_uso_solo": "",
    }

    # Download da imagem de satélite bruta
    try:
        baixar_imagem(
            wms_url=cfg["wms_url"],
            camada=cfg["camada_satelite"],
            bbox=bbox,
            caminho_saida=caminho_satelite,
            largura_pixels=cfg["largura_pixels"],
            altura_pixels=cfg["altura_pixels"],
            srid=cfg["srid_wms"],
            wms_versao=cfg["wms_versao"],
            formato=cfg["formato_wms"],
            transparente=cfg["transparente"],
            epsg_codigo=cfg["epsg_codigo"],
            timeout=cfg["timeout_requisicao"],
            tentativas=cfg["tentativas_por_imagem"],
            pausa_entre_tentativas=cfg["pausa_entre_tentativas"],
        )
        resultado["status_satelite"] = "ok"
        resultado["hash_satelite"] = calcular_hash_sha256(caminho_satelite)
        logger.info(f"[{cod_imovel}] satelite.tif OK")
    except Exception as erro:
        logger.error(f"[{cod_imovel}] Falha ao baixar satelite.tif: {erro}")

    # Download do mapa de uso do solo
    try:
        baixar_imagem(
            wms_url=cfg["wms_url"],
            camada=cfg["camada_uso_solo"],
            bbox=bbox,
            caminho_saida=caminho_uso_solo,
            largura_pixels=cfg["largura_pixels"],
            altura_pixels=cfg["altura_pixels"],
            srid=cfg["srid_wms"],
            wms_versao=cfg["wms_versao"],
            formato=cfg["formato_wms"],
            transparente=cfg["transparente"],
            epsg_codigo=cfg["epsg_codigo"],
            timeout=cfg["timeout_requisicao"],
            tentativas=cfg["tentativas_por_imagem"],
            pausa_entre_tentativas=cfg["pausa_entre_tentativas"],
        )
        resultado["status_uso_solo"] = "ok"
        resultado["hash_uso_solo"] = calcular_hash_sha256(caminho_uso_solo)
        logger.info(f"[{cod_imovel}] uso_solo.tif OK")
    except Exception as erro:
        logger.error(f"[{cod_imovel}] Falha ao baixar uso_solo.tif: {erro}")

    return resultado


def executar_pipeline() -> None:
    """
    Função principal do pipeline. Orquestra leitura do CSV, filtragem de imóveis
    já processados, downloads paralelos e registro no manifesto.
    """
    cfg = CONFIGURACOES

    configurar_logging(cfg["pasta_logs"], cfg["nome_log"])
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Iniciando pipeline de extração IntegraCar")
    logger.info("=" * 60)

    # Inicializar manifesto (cria arquivo com cabeçalho se ainda não existe)
    caminho_manifesto = Path(cfg["pasta_artifacts"]) / cfg["nome_manifesto"]
    inicializar_manifesto(caminho_manifesto)

    # Ler CSV de coordenadas
    dataframe = pd.read_csv(cfg["arquivo_csv"], sep=cfg["separador_csv"])
    total_imoveis = len(dataframe)
    logger.info(f"CSV carregado: {total_imoveis} imóveis encontrados")

    # Filtrar imóveis já processados com sucesso (idempotência)
    if cfg["pular_se_existir"]:
        ja_processados = carregar_imoveis_processados(caminho_manifesto)
        dataframe_pendente = dataframe[~dataframe["cod_imovel"].isin(ja_processados)]
        logger.info(
            f"Já processados: {len(ja_processados)} | Pendentes: {len(dataframe_pendente)}"
        )
    else:
        dataframe_pendente = dataframe

    if dataframe_pendente.empty:
        logger.info("Todos os imóveis já foram processados. Pipeline encerrado.")
        return

    # Criar pasta de saída principal
    Path(cfg["pasta_saida"]).mkdir(parents=True, exist_ok=True)

    # Processar imóveis com download paralelo
    contagem_sucesso = 0
    contagem_erro = 0

    with ThreadPoolExecutor(max_workers=cfg["workers_paralelos"]) as executor:
        futures = {
            executor.submit(
                processar_imovel,
                row["cod_imovel"],
                row["x"],
                row["y"],
                cfg,
            ): row["cod_imovel"]
            for _, row in dataframe_pendente.iterrows()
        }

        with tqdm(total=len(futures), desc="Baixando imagens", unit="imóvel") as barra_progresso:
            for future in as_completed(futures):
                resultado = future.result()

                registrar_resultado(
                    caminho_manifesto=caminho_manifesto,
                    cod_imovel=resultado["cod_imovel"],
                    x=resultado["x"],
                    y=resultado["y"],
                    bbox=resultado["bbox"],
                    status_satelite=resultado["status_satelite"],
                    status_uso_solo=resultado["status_uso_solo"],
                    hash_satelite=resultado["hash_satelite"],
                    hash_uso_solo=resultado["hash_uso_solo"],
                )

                if resultado["status_satelite"] == "ok" and resultado["status_uso_solo"] == "ok":
                    contagem_sucesso += 1
                else:
                    contagem_erro += 1

                barra_progresso.update(1)

    logger.info("=" * 60)
    logger.info(f"Pipeline concluído.")
    logger.info(f"Pares completos (ok/ok): {contagem_sucesso}")
    logger.info(f"Com erro: {contagem_erro}")
    logger.info(f"Manifesto salvo em: {caminho_manifesto}")
    logger.info("=" * 60)


if __name__ == "__main__":
    executar_pipeline()
```

---

## FLUXO DE EXECUÇÃO PASSO A PASSO

```
python extrator.py
        │
        ▼
configurar_logging()
        │
        ▼
inicializar_manifesto()   ← cria artifacts/dataset_manifesto.csv se não existir
        │
        ▼
pd.read_csv("coordenadas_treino_amostra.csv")
        │
        ▼
carregar_imoveis_processados()   ← lê manifesto para saber o que pular
        │
        ▼
filtrar dataframe_pendente
        │
        ▼
ThreadPoolExecutor(workers=4)
        │
        ▼ (para cada imóvel em paralelo)
processar_imovel(cod_imovel, x, y)
        │
        ├── calcular_bbox(x, y, buffer=512)
        │       └── (x-512, y-512, x+512, y+512)
        │
        ├── baixar_imagem(camada_satelite, bbox) ─────────────────►  GET WMS
        │       ├── montar_parametros_wms()                           GeoBases
        │       ├── requisitar_imagem_wms()  (retry até 3×)  ◄────── bytes TIF
        │       └── salvar_como_geotiff()
        │               ├── PIL decode → numpy array (1024, 1024, 3)
        │               ├── from_bounds() → transform afim
        │               └── rasterio.open(driver=GTiff, crs=31984)
        │
        ├── calcular_hash_sha256(satelite.tif)
        │
        ├── baixar_imagem(camada_uso_solo, bbox)  ─────────────────►  GET WMS
        │       └── (mesmo processo acima)                ◄────────── bytes TIF
        │
        └── calcular_hash_sha256(uso_solo.tif)
                │
                ▼
        registrar_resultado() → append linha no manifesto CSV
                │
                ▼
        tqdm.update()
```

---

## VALIDAÇÃO — Como verificar se o pipeline funcionou corretamente

### 1. Verificar estrutura de arquivos gerados
```bash
ls saida/ | head -5
ls saida/ES-3200136-AED7CD85F9FA458FBC0774E88DF33101/
# Esperado: satelite.tif  uso_solo.tif
```

### 2. Verificar o GeoTIFF com Python manualmente
```python
import rasterio
import numpy as np

with rasterio.open("saida/ES-3200136-AED7CD85F9FA458FBC0774E88DF33101/satelite.tif") as arquivo:
    print("Dimensões:", arquivo.width, "x", arquivo.height)  # deve ser 1024 x 1024
    print("Bandas:", arquivo.count)                          # deve ser 3
    print("CRS:", arquivo.crs)                               # deve ser EPSG:31984
    print("Transform:", arquivo.transform)
    print("Dtype:", arquivo.dtypes)                          # deve ser ('uint8', 'uint8', 'uint8')
    imagem = arquivo.read()
    print("Shape do array:", imagem.shape)                   # deve ser (3, 1024, 1024)
    print("Valores nulos?", np.all(imagem == 0))             # False = imagem tem conteúdo
```

### 3. Verificar o manifesto
```python
import pandas as pd
manifesto = pd.read_csv("artifacts/dataset_manifesto.csv", sep=";")
print(manifesto["status_satelite"].value_counts())
print(manifesto["status_uso_solo"].value_counts())
print(f"Pares completos: {(manifesto['status_satelite'] == 'ok').sum()}")
```

### 4. Visualizar uma imagem no QGIS
Arrastar o arquivo `satelite.tif` para o QGIS. A camada deve aparecer georreferenciada na posição correta do Espírito Santo — se o arquivo tiver CRS e transform corretos, ele se sobreporá com precisão ao mapa base.

---

## PONTOS DE ATENÇÃO E TRATAMENTO DE ERROS

### O servidor retornar XML/HTML ao invés de imagem
Isso acontece quando o typename da camada está errado ou quando a requisição está malformada. O `wms.py` detecta isso pelo `Content-Type` da resposta e lança `RuntimeError` com o conteúdo da resposta, que vai para o log.

### Imagem com pixels todos zeros (imagem preta)
Indica que o bbox solicitado está fora da cobertura da camada naquele servidor. Verificar com:
```python
if np.all(imagem == 0):
    logger.warning(f"[{cod_imovel}] Imagem vazia — ponto fora da cobertura da camada")
```
Essa validação pode ser adicionada dentro de `salvar_como_geotiff` como uma checagem opcional.

### Rate limiting do GeoBases
Se muitas requisições simultâneas resultarem em respostas HTTP 429 ou 503, reduzir `workers_paralelos` para 1 ou 2 e aumentar `pausa_entre_tentativas` em `configuracoes.py`.

### Execução interrompida no meio
O pipeline é idempotente por design. Basta rodar `python extrator.py` novamente — ele lê o manifesto, identifica o que já foi processado com sucesso (`status == "ok"`) e retoma a partir do que falta.

---

## RESUMO DA STACK TÉCNICA

| Componente | Tecnologia | Justificativa |
|---|---|---|
| Linguagem | Python 3.14 | Ecossistema geoespacial maduro, domínio da equipe |
| Leitura do CSV | `pandas` | Simples, robusto, compatível com separador `;` |
| Requisições HTTP | `requests` | Não bloqueante, suporte a timeout e retry |
| Decodificação de imagem | `Pillow` | Decodifica a resposta binária TIF/PNG do WMS |
| Manipulação de arrays | `numpy` | Transpor shape (H,W,C) → (C,H,W) para rasterio |
| GeoTIFF georreferenciado | `rasterio` | Única biblioteca que grava CRS e transform afim |
| Progresso visual | `tqdm` | Barra de progresso durante download em lote |
| Downloads paralelos | `concurrent.futures` | Embutido no Python, sem dependência extra |
| Integridade de dados | `hashlib` SHA256 | Embutido no Python, detecta corrupção |
| Logging | `logging` | Embutido no Python, grava em arquivo e terminal |
