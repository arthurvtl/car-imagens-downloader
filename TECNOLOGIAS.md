# Tecnologias e Bibliotecas

Referencia das bibliotecas utilizadas no pipeline IntegraCar, com descricao do
papel de cada uma no projeto.

---

## pandas

**Versao minima:** `>= 2.2.3`

Biblioteca de analise e manipulacao de dados tabulares. No projeto, e usada para
ler o CSV de entrada com as coordenadas UTM das propriedades rurais.

- Le o arquivo com `pd.read_csv(arquivo, sep=";")` e retorna um `DataFrame`
- Permite truncar para as primeiras N linhas com `.head(N)`
- Itera linha a linha com `.iterrows()` para alimentar os pipelines

---

## aiohttp

**Versao minima:** `>= 3.9.0`

Cliente HTTP assincrono para Python, baseado em `asyncio`. Responsavel por toda
a comunicacao de rede com o servidor WMS do GeoBases.

- Envia requisicoes `GET` ao endpoint WMS com os parametros do `GetMap`
- Usa `TCPConnector` com pool de conexoes para reutilizar sockets TCP (keep-alive)
- Configura timeout por requisicao (`ClientTimeout`) para evitar travamentos
- Em caso de falha, retenta ate 3 vezes com pausa entre tentativas

Trabalha em conjunto com `asyncio` para permitir downloads simultaneos.

---

## asyncio

**Origem:** biblioteca padrao do Python (nao requer instalacao)

Motor de concorrencia assincrona do Python. Permite executar multiplas operacoes
de I/O simultaneamente sem usar multiplas threads ou processos.

| Recurso | Uso no projeto |
|---------|----------------|
| `Semaphore` | Limita quantos downloads ocorrem ao mesmo tempo |
| `gather` | Dispara download do satelite e uso do solo em paralelo para cada amostra |
| `as_completed` | Processa resultados a medida que ficam prontos |
| `run_in_executor` | Executa conversao PNG->GeoTIFF (CPU-bound) sem bloquear o event loop |

---

## requests

**Versao minima:** `>= 2.32.3`

Cliente HTTP sincrono. Usado no pipeline 2012-2015 para o download do arquivo
ZIP do shapefile de uso do solo, com suporte a streaming (`stream=True`) para
acompanhar progresso e nao carregar o arquivo inteiro em memoria.

---

## OWSLib

**Versao minima:** `>= 0.29.3`

Biblioteca para consumir servicos geoespaciais OGC (WMS, WFS, WCS). No projeto,
e usada apenas na fase de inicializacao e validacao.

- Conecta ao servidor WMS via `WebMapService(url, version="1.3.0")`
- Baixa automaticamente o `GetCapabilities` (catalogo de camadas)
- Permite verificar se as camadas necessarias existem no servidor

Nao e usada para os downloads em si (esses sao feitos com `aiohttp`).

---

## pyproj

**Versao minima:** `>= 3.6.1`

Biblioteca de transformacoes cartograficas, baseada na biblioteca C `PROJ`.
Converte coordenadas entre sistemas de referencia.

No projeto, converte de **EPSG:31984** (UTM zona 24S, metros) para **EPSG:4326**
(latitude/longitude, graus decimais), que e o sistema exigido pelo servidor WMS.

- Cria um `Transformer` com `from_crs("EPSG:31984", "EPSG:4326", always_xy=True)`
- Aplica a transformacao nos quatro cantos do bounding box de cada ponto
- O transformador e criado uma unica vez e reutilizado em cache

---

## Pillow

**Versao minima:** `>= 11.1.0`

Biblioteca de processamento de imagens. No pipeline, decodifica os bytes PNG
retornados pelo servidor WMS em uma imagem RGB manipulavel:

```python
imagem_pil = Image.open(io.BytesIO(conteudo_binario)).convert("RGB")
```

O conteudo binario recebido via HTTP e carregado diretamente da memoria usando
`io.BytesIO`, sem tocar o disco.

---

## numpy

**Versao minima:** `>= 2.2.3`

Biblioteca de computacao numerica com arrays multidimensionais. Serve de ponte
entre Pillow e rasterio:

```python
array_imagem = np.array(imagem_pil)   # shape: (altura, largura, 3)
```

O `rasterio` espera os dados no formato `(bandas, altura, largura)`. O numpy
faz a transposicao com `.transpose(2, 0, 1)` antes de gravar o GeoTIFF.

No pipeline 2012-2015, numpy tambem e usado para:
- Construir o array RGB da imagem de uso do solo a partir da rasterizacao
- Calcular porcentagem de pixels pintados na analise de cobertura

---

## rasterio

**Versao minima:** `>= 1.4.3`

Biblioteca geoespacial de referencia para leitura e escrita de dados raster
(imagens georreferenciadas). Responsavel por criar os arquivos GeoTIFF.

- Recebe o array numpy com os pixels da imagem
- Recebe a transformacao afim (`from_bounds`) que mapeia pixels a posicoes reais
- Recebe o CRS (`CRS.from_epsg(4326)`) embutido no arquivo
- Grava o `.tif` com compressao LZW (sem perda de qualidade)

O submodulo `rasterio.features.rasterize` e usado no pipeline 2012-2015 para
converter geometrias vetoriais (poligonos do shapefile) em uma grade raster
com os IDs de cada classe de uso do solo.

---

## geopandas

**Versao minima:** `>= 1.0.1`

Extensao do pandas para dados geoespaciais. Usado no pipeline 2012-2015 para:

- Carregar o shapefile de uso do solo com `gpd.read_file()`
- Reprojetar para EPSG:4326 com `.to_crs()`
- Recortar poligonos por bounding box com `.cx[minx:maxx, miny:maxy]`

---

## shapely

**Versao minima:** `>= 2.0.6`

Biblioteca de manipulacao de geometrias planares. Dependencia do geopandas para
representacao e operacoes sobre poligonos, pontos e linhas.

---

## tkinter

**Origem:** biblioteca padrao do Python (nao requer instalacao)

Framework de interface grafica nativo do Python. Usado para construir a janela
principal da aplicacao com:

- Campos de entrada (CSV, pasta de saida, buffer, quantidade)
- Combobox de selecao de ano
- Checkbox de download simultaneo e manutencao do shapefile
- Barra de progresso com atualizacao thread-safe
- Callbacks `root.after()` para atualizacoes seguras a partir de threads

---

## Bibliotecas padrao

Modulos nativos usados para infraestrutura do pipeline:

| Modulo | Uso no projeto |
|--------|----------------|
| `csv` (`DictWriter`) | Le e escreve o manifesto `dataset_manifesto.csv` em modo append |
| `logging` | Grava eventos com timestamp em `logs/execucao.log` e no terminal |
| `pathlib.Path` | Manipula caminhos de forma independente de SO |
| `datetime` | Gera timestamp ISO 8601 registrado no manifesto |
| `threading` | Executa pipelines em threads separadas sem bloquear a GUI |
| `time` | Mede tempos de cada etapa e calcula estimativas de conclusao |
| `zipfile` | Extrai o shapefile 2012-2015 do arquivo ZIP baixado |
| `shutil` | Remove arquivos temporarios (shapefile) apos processamento |
| `os` | Navegacao em diretorios para localizar o `.shp` dentro do ZIP |

---

## Resumo

| Biblioteca | Papel principal |
|------------|-----------------|
| `pandas` | Leitura e filtragem do CSV de coordenadas |
| `aiohttp` | Requisicoes HTTP assincronas ao servidor WMS |
| `asyncio` | Motor de concorrencia: paralelismo de downloads e semaforo |
| `requests` | Download sincrono do shapefile 2012-2015 (ZIP) |
| `OWSLib` | Conexao inicial e validacao das camadas WMS |
| `pyproj` | Conversao de coordenadas UTM -> lat/lon |
| `Pillow` | Decodificacao de PNG binario em imagem RGB |
| `numpy` | Ponte numerica entre Pillow e rasterio + analise de pixels |
| `rasterio` | Geracao de GeoTIFFs georreferenciados + rasterizacao |
| `geopandas` | Leitura, reprojecao e recorte do shapefile 2012-2015 |
| `shapely` | Manipulacao de geometrias (dependencia do geopandas) |
| `tkinter` | Interface grafica da aplicacao |
| `csv` | Leitura e escrita do manifesto CSV |
| `logging` | Log com timestamp em arquivo e terminal |
| `threading` | Execucao paralela dos pipelines sem bloquear a GUI |
| `time` | Medicao de tempos e estimativas de conclusao |
