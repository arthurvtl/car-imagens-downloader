# IntegraCar -- Pipeline de Extracao de Imagens

Pipeline automatizado que baixa imagens de satelite e mapas de uso do solo do
**GeoBases do Espirito Santo** para propriedades rurais cadastradas no CAR
(Cadastro Ambiental Rural).

Para cada coordenada listada em um arquivo CSV, o pipeline produz dois arquivos
GeoTIFF georreferenciados (satelite + uso do solo), em um dos dois periodos:

- **2012-2015** -- ortofoto 0,25m (IEMA) + uso do solo rasterizado a partir de shapefile
- **2019-2020** -- ortofoto KOMPSAT 3/3A (IJSN) + uso do solo via WMS

---

## Instalacao

```bash
git clone <url-do-repositorio>
cd projeto-automacao
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

---

## Como Usar

A aplicacao e operada por uma **interface grafica** (Tkinter). Para abrir:

```bash
python extrator.py
```

### Campos da interface

| Campo                     | Descricao                                                       |
|---------------------------|-----------------------------------------------------------------|
| Arquivo CSV de Entrada    | CSV com colunas `cod_imovel;x;y` (separadas por `;`)           |
| Pasta de Saida            | Destino das imagens (modo individual)                           |
| Buffer (metros)           | Metade do lado do recorte geografico em metros (padrao: 1024)   |
| Quantidade de Imagens     | Limita as primeiras N linhas do CSV (vazio = todas)             |
| Ano                       | Periodo de processamento: `2012-2015` ou `2019-2020`           |
| Download simultaneo       | Checkbox que habilita execucao paralela dos dois periodos       |
| Pasta Saida 12-15         | Destino das imagens 2012-2015 (visivel no modo simultaneo)      |
| Pasta Saida 19-20         | Destino das imagens 2019-2020 (visivel no modo simultaneo)      |
| Manter Shapefile          | Preserva o shapefile baixado apos processamento 2012-2015       |

### Modo simultaneo

Ao marcar "Download simultaneo 12-15, 19-20", a interface pede dois caminhos de
saida (um para cada periodo). O buffer e a quantidade sao compartilhados.
Os dois pipelines rodam em threads paralelas.

---

## Estrutura de Saida

### Periodo 2012-2015

```
pasta_saida_1215/
  amostra_1_satelite_2012.tif
  amostra_1_uso_solo_2012.tif
  amostra_2_satelite_2012.tif
  amostra_2_uso_solo_2012.tif
  ...
```

### Periodo 2019-2020

```
pasta_saida_1920/
  amostra_1_satelite_1920.tif
  amostra_1_uso_solo_1920.tif
  amostra_2_satelite_1920.tif
  amostra_2_uso_solo_1920.tif
  ...
```

### Artefatos e logs

```
artifacts/
  dataset_manifesto.csv       <- registro de status de cada download (19-20)
  imagens_cheias_12-15.txt    <- amostras 100% pintadas (12-15)
  imagens_incompletas_12-15.txt <- amostras com pixels faltando (12-15)

logs/
  execucao.log                <- log completo da execucao
```

---

## Como o Pipeline Funciona

### Pipeline 2019-2020

| Etapa | Descricao |
|-------|-----------|
| 1/4   | Conecta ao servico WMS do GeoBases e valida as camadas |
| 2/4   | Le o CSV de coordenadas e aplica limite de quantidade |
| 3/4   | Baixa pares satelite+uso_solo de forma assincrona (aiohttp) |
| 4/4   | Exibe resumo com totais e tempos |

Cada coordenada e convertida de EPSG:31984 (UTM 24S) para EPSG:4326 (lat/lon),
gerando um bounding box que delimita a regiao a recortar. O download das duas
imagens de cada amostra acontece em paralelo via `asyncio.gather`. O numero de
workers simultaneos e controlado por um semaforo.

### Pipeline 2012-2015

| Etapa | Descricao |
|-------|-----------|
| 1/6   | Baixa o shapefile de uso do solo 2012-2015 (ZIP ~200MB) |
| 2/6   | Extrai o ZIP em pasta temporaria |
| 3/6   | Le o CSV de coordenadas |
| 4/6   | Carrega o shapefile na memoria e reprojeta para EPSG:4326 |
| 5/6   | Para cada ponto: baixa satelite via WMS + rasteriza uso do solo |
| 6/6   | Analisa cobertura das imagens e gera relatorios |

A imagem de uso do solo 2012 nao vem do WMS -- ela e construida rasterizando os
poligonos do shapefile dentro do bbox de cada amostra, pintando cada classe com
a cor correspondente da paleta oficial.

Apos o processamento, o modulo `analisa_img_12_15.py` verifica se cada imagem
esta 100% pintada (sem pixels pretos) e gera dois relatorios TXT.

---

## Saida no Terminal

Ambos os pipelines produzem saida padronizada no terminal:

```
[ETAPA 1/4] Conectando ao servico WMS (2019-2020)...
  -> Camada validada: geonode:ijsn-ortofotomosaico-es-kompsat-3-3a-2019-2020
  -> Camada validada: geonode:ijsn_map_uso_solo_es_2019_20200
  -> Conexao WMS estabelecida em 2.3s
[ETAPA 2/4] Lendo CSV de coordenadas...
  -> 10 coordenadas para processar
[ETAPA 3/4] Baixando imagens (0/10)...
  [amostra_1/10] OK em 1.2s (media 1.2s/par -- restante ~11s)
  [amostra_3/10] OK em 1.5s (media 1.4s/par -- restante ~10s)
  ...
============================================================
  Pares processados: 10/10
  Pares completos:   10
  Com erro:          0
  Tempo total:       15.3s
  Media por par:     1.53s
============================================================
```

---

## Formato do CSV de Entrada

Separador: **ponto-e-virgula** (`;`)

| Coluna       | Tipo   | Descricao                                       |
|--------------|--------|-------------------------------------------------|
| `cod_imovel` | string | Codigo do imovel no CAR                         |
| `x`          | float  | Coordenada X em metros (EPSG:31984 -- UTM 24S)  |
| `y`          | float  | Coordenada Y em metros (EPSG:31984)             |

---

## Estrutura do Projeto

```
projeto-automacao/
  extrator.py             <- ponto de entrada: GUI + pipelines 2012 e 2019-2020
  configuracoes.py        <- configuracoes internas (URLs WMS, camadas, defaults)
  analisa_img_12_15.py    <- analise de cobertura de pixels das imagens 2012-2015
  requirements.txt        <- dependencias Python

  utils/
    wms.py                <- download WMS, conversao bbox, geracao de GeoTIFF
    manifesto.py          <- leitura e escrita do CSV de manifesto

  artifacts/              <- gerado automaticamente (manifesto + relatorios)
  logs/                   <- gerado automaticamente (log de execucao)
```

---

## Diagrama do Fluxo

```
coordenadas.csv
      |
      v
 [pandas] le o CSV
      |
      v  para cada coordenada
      |
      +---> [pyproj] converte UTM -> lat/lon -> calcula bbox
      |
      +---> Pipeline 2019-2020:
      |       [aiohttp + asyncio] GetMap ao GeoBases WMS
      |       SATELITE + USO_SOLO em paralelo (asyncio.gather)
      |       [Pillow] decodifica PNG -> RGB
      |       [numpy + rasterio] grava GeoTIFF georreferenciado
      |       [csv] registra resultado no manifesto
      |
      +---> Pipeline 2012-2015:
      |       [requests] baixa shapefile ZIP
      |       [geopandas] carrega e reprojeta shapefile
      |       [aiohttp] baixa satelite via WMS
      |       [rasterio.features] rasteriza uso do solo do shapefile
      |       [numpy + rasterio] grava GeoTIFF georreferenciado
      |       [analisa_img_12_15] verifica cobertura de pixels
      |
      v
 [logging] grava eventos no log
```
