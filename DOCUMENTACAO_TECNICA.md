# Documentação Técnica

## Visão Geral

O projeto é um pipeline geoespacial para extrair imagens de satélite e máscaras de uso do solo a partir de coordenadas de imóveis rurais do CAR. A entrada principal é um CSV com coordenadas em UTM (`EPSG:31984`), e a saída são arquivos GeoTIFF georreferenciados organizados por amostra.

O problema resolvido é a geração automatizada de pares de imagens para análise territorial:

- imagem de satélite da área ao redor de um ponto;
- imagem segmentada de uso do solo da mesma área;
- mesma resolução espacial, mesmo recorte e mesma referência geográfica.

A versão `extrator-sem-rgb.py` é a variante principal desta branch. Ela busca padronizar as imagens segmentadas como máscaras de 1 banda, onde cada pixel contém o ID numérico da classe de uso do solo, em vez de uma cor RGB.

## Fluxo Principal

O fluxo da aplicação é:

1. A entrada pode vir pela interface Tkinter ou por chamada via terminal/script.
2. A aplicação recebe o CSV, pasta de saída, buffer, quantidade de imagens e período.
3. O CSV é carregado com `pandas`.
4. Para cada linha, o sistema calcula um BBOX ao redor da coordenada central.
5. O BBOX é convertido de `EPSG:31984` para `EPSG:4326`.
6. O pipeline correspondente ao período é executado:
   - `2019-2020`: baixa satélite e uso do solo via WMS.
   - `2012-2015`: baixa satélite via WMS e rasteriza uso do solo a partir de shapefile.
7. As imagens são persistidas como GeoTIFF.
8. Logs, manifesto e relatórios auxiliares são gerados em disco.

## Stack Utilizada

### Python

Python é a linguagem base do projeto. Foi escolhido por causa do ecossistema maduro para processamento geoespacial, manipulação de dados tabulares, rasterização e automação de downloads.

Ele sustenta toda a aplicação:

- interface gráfica;
- leitura do CSV;
- consumo de WMS;
- processamento raster/vector;
- escrita de GeoTIFF;
- concorrência assíncrona.

### CLI / execução por terminal

O projeto não usa um framework de CLI como `argparse`, `click` ou `typer`. Mesmo assim, ele pode ser operado via terminal de duas formas:

- abrindo a interface gráfica com `python extrator-sem-rgb.py`;
- chamando diretamente as funções de pipeline em uma execução Python.

A segunda opção é útil para automação, processamento em lote e integração com scripts externos. Como o arquivo principal da branch tem hífen no nome (`extrator-sem-rgb.py`), a importação direta exige `importlib`.

Exemplo para `2019-2020`:

```bash
python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('extrator_sem_rgb', 'extrator-sem-rgb.py'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); mod.processar_ano_2019_2020('coordenadas_treino_amostra.csv', 'saida_1920', 1024, 10)"
```

Exemplo para `2012-2015`:

```bash
python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('extrator_sem_rgb', 'extrator-sem-rgb.py'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); cb = lambda *args, **kwargs: None; mod.processar_ano_2012('coordenadas_treino_amostra.csv', 'saida_1215', 1024, 10, False, cb, cb)"
```

Os argumentos seguem a assinatura das funções:

```python
processar_ano_2019_2020(
    arquivo_csv,
    pasta_saida,
    buffer_metros,
    qtd_imagens,
)

processar_ano_2012(
    arquivo_csv,
    pasta_saida,
    buffer_metros,
    qtd_imagens,
    manter_shapefile,
    atualizar_status,
    atualizar_progresso,
)
```

No caso de `2012-2015`, os callbacks são obrigatórios porque o mesmo pipeline é usado pela GUI. Em uso via CLI, eles podem ser funções simples que não fazem nada, como `lambda *args, **kwargs: None`.

### Tkinter

Tkinter é a biblioteca padrão de GUI do Python. O projeto usa Tkinter para expor uma interface simples de operação sem depender de frontend web.

Na arquitetura, ele atua apenas como camada de entrada e controle:

- coleta caminhos e parâmetros;
- dispara pipelines em threads;
- atualiza status e barra de progresso;
- não contém regra geoespacial relevante.

Trecho central:

```python
threading.Thread(target=_worker, daemon=True).start()
```

Essa separação evita que a GUI trave enquanto o pipeline executa downloads e processamento.

### pandas

`pandas` é usado para ler e filtrar o CSV de entrada. O projeto espera colunas como `cod_imovel`, `x` e `y`, separadas por ponto-e-vírgula.

Ele entra logo no início dos pipelines, transformando o CSV em um `DataFrame` iterável:

```python
dataframe = pd.read_csv(
    cfg["arquivo_csv"], sep=CONFIGURACOES["separador_csv"]
)
```

Também é usado para limitar a quantidade de amostras:

```python
if limite and limite < total_csv:
    dataframe = dataframe.head(limite)
```

### WMS

WMS, ou Web Map Service, é um padrão OGC para disponibilizar mapas e imagens geográficas por HTTP. O projeto usa WMS para obter imagens renderizadas do GeoBases/ES.

O WMS é usado em dois pontos:

- satélite `2019-2020`;
- uso do solo `2019-2020`;
- satélite `2012-2015`.

As camadas são definidas em `configuracoes.py`:

```python
"wms_url": "https://ide.geobases.es.gov.br/geoserver/ows",
"camada_satelite": "geonode:ijsn-ortofotomosaico-es-kompsat-3-3a-2019-2020",
"camada_uso_solo": "geonode:ijsn_map_uso_solo_es_2019_20200",
"camada_satelite_2012": "geonode:iema_ortofotomosaico_es_025m_2012-2015",
```

O projeto monta requisições `GetMap`, informando camada, BBOX, CRS, altura, largura e formato.

```python
return {
    "service": "WMS",
    "version": wms_versao,
    "request": "GetMap",
    "layers": camada,
    "bbox": bbox_str,
    "width": largura_pixels,
    "height": altura_pixels,
    "crs": srid,
    "format": formato,
    "styles": "",
}
```

### OWSLib

`OWSLib` é usado para conectar ao WMS e validar se as camadas esperadas existem no catálogo do servidor.

Ele não faz os downloads das imagens. Sua função é de validação e descoberta:

```python
wms = WebMapService(wms_url, version=wms_versao)
return nome_camada in wms.contents
```

Essa escolha separa validação de catálogo da etapa de download, que fica com `aiohttp`.

### aiohttp

`aiohttp` é usado como cliente HTTP assíncrono para baixar imagens WMS. Foi escolhido porque o pipeline `2019-2020` precisa baixar muitos pares de imagens e o gargalo principal é I/O de rede.

Ele entra na arquitetura como camada de comunicação HTTP concorrente:

```python
async with sessao.get(
    wms_url, params=parametros, timeout=timeout_cfg
) as resposta:
    resposta.raise_for_status()
    return await resposta.read()
```

O projeto também usa retry simples para lidar com falhas temporárias do servidor.

### asyncio

`asyncio` coordena concorrência no pipeline de 2019-2020. Ele permite processar várias amostras em paralelo sem abrir uma thread para cada requisição.

Dois níveis de paralelismo aparecem no código:

- várias amostras em paralelo, controladas por `Semaphore`;
- satélite e uso do solo de uma mesma amostra baixados em paralelo com `asyncio.gather`.

```python
status_satelite, status_uso_solo = await asyncio.gather(
    _baixar_uma_imagem_async(sessao, cfg, cfg["camada_satelite"], bbox, caminho_satelite),
    _baixar_uma_imagem_async(sessao, cfg, cfg["camada_uso_solo"], bbox, caminho_uso_solo),
)
```

O impacto é direto no tempo total do pipeline, especialmente quando há muitas coordenadas.

### requests

`requests` é usado apenas no fluxo `2012-2015` para baixar o ZIP do shapefile de uso do solo.

Esse download é síncrono porque ocorre uma única vez antes do processamento das amostras:

```python
with requests.get(url_zip, stream=True) as resposta:
    resposta.raise_for_status()
```

Como o arquivo é grande, o projeto usa streaming e escreve em chunks.

### pyproj

`pyproj` faz a transformação de coordenadas entre sistemas de referência.

O CSV usa `EPSG:31984`, mas o WMS trabalha com `EPSG:4326`. Por isso, antes de consultar o GeoBases, o projeto converte os cantos do BBOX:

```python
transformador = Transformer.from_crs(
    srid_entrada, "EPSG:4326", always_xy=True
)
lon_min, lat_min = transformador.transform(xmin_utm, ymin_utm)
lon_max, lat_max = transformador.transform(xmax_utm, ymax_utm)
```

O transformador é cacheado em memória para evitar recriação a cada amostra.

### RasterIO

`rasterio` é a principal biblioteca de raster do projeto. Ela grava GeoTIFFs com CRS, transformada espacial e compressão.

No download WMS, o PNG retornado pelo servidor é convertido para GeoTIFF:

```python
with rasterio.open(
    caminho,
    "w",
    driver="GTiff",
    height=altura_pixels,
    width=largura_pixels,
    count=3,
    dtype="uint8",
    crs=crs,
    transform=transform_afim,
    compress="lzw",
) as dataset_raster:
    dataset_raster.write(array_imagem.transpose(2, 0, 1))
```

No fluxo `2012-2015`, `rasterio.features.rasterize` transforma geometrias vetoriais do shapefile em máscara raster.

### GeoPandas

`GeoPandas` é usado no pipeline `2012-2015` para ler, reprojetar e recortar o shapefile de uso do solo.

Ele entra na arquitetura como camada vetorial:

```python
gdf_uso_solo = gpd.read_file(shapefile_encontrado)
gdf_uso_solo = gdf_uso_solo.to_crs(srid_wms)
gdf_recorte = gdf_uso_solo.cx[minx:maxx, miny:maxy]
```

O `.cx` é usado para reduzir o conjunto de geometrias ao BBOX da amostra antes da rasterização.

### NumPy

`NumPy` representa pixels como arrays. Ele é usado como ponte entre imagem, raster e lógica de máscara.

Exemplos:

- converter imagem RGB em array;
- comparar pixels por cor;
- montar máscara de IDs;
- detectar pixels vazios na análise de cobertura.

Na branch sem RGB, o uso mais importante é converter a imagem WMS de uso do solo para IDs:

```python
mascara = (dados[0] == r) & (dados[1] == g) & (dados[2] == b)
ids_array[mascara] = classe_id
```

### Pillow

`Pillow` decodifica a imagem PNG retornada pelo WMS. O WMS entrega bytes; o projeto precisa transformar esses bytes em matriz de pixels antes de gravar GeoTIFF.

```python
imagem_pil = Image.open(io.BytesIO(conteudo_binario)).convert("RGB")
array_imagem = np.array(imagem_pil)
```

### Shapely

`Shapely` é uma dependência geoespacial usada indiretamente pelo GeoPandas para representar e manipular geometrias.

O projeto não chama muitas APIs de Shapely diretamente. A geometria aparece principalmente em:

```python
for geom, classe_id_val in zip(gdf_recorte.geometry, gdf_recorte[col_id]):
    shapes.append((geom, id_novo))
```

Essas geometrias são entregues ao `rasterize`.

### Logging

`logging` registra eventos em arquivo e terminal. Ele ajuda a auditar falhas de rede, erros por amostra, camadas ausentes e resumo de execução.

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(caminho_log, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
```

## Tecnologias Não Usadas

Alguns conceitos comuns em pipelines geoespaciais não aparecem neste projeto:

- STAC API: não há busca em catálogos STAC nem consulta temporal por assets.
- Banco de dados: os dados são lidos de CSV e persistidos em arquivos.
- Backend web: não existe API HTTP própria.
- Frontend web: a interface é desktop com Tkinter.
- Filas externas: não há Celery, Redis, RabbitMQ ou fila persistente.
- Tiles XYZ/WMTS: o projeto usa WMS `GetMap`, não mosaico em tiles.
- NDVI ou bandas espectrais: não há cálculo espectral; as imagens são tratadas como RGB ou máscara categórica.

## Arquitetura de Pastas

```text
IMG-EXTRACTOR/
  extrator-sem-rgb.py          # Pipeline principal da branch sem RGB
  extrator.py                  # Versão original com máscaras RGB
  configuracoes.py             # Configurações globais de WMS, CRS e execução
  analisa_img_12_15.py         # Análise de cobertura das máscaras 2012-2015
  coordenadas_treino_amostra.csv
  requirements.txt
  utils/
    wms.py                     # WMS, BBOX, download e GeoTIFF
    manifesto.py               # Escrita do manifesto CSV
```

## Responsabilidades dos Módulos

### `extrator-sem-rgb.py`

É o orquestrador principal. Contém:

- dicionário de classes e IDs;
- conversão RGB para ID no uso do solo `2019-2020`;
- pipeline assíncrono `2019-2020`;
- pipeline vetorial/raster `2012-2015`;
- interface Tkinter;
- controle de threads da GUI.

### `utils/wms.py`

Centraliza a integração com WMS:

- conexão e validação de camadas;
- cálculo de BBOX;
- montagem dos parâmetros `GetMap`;
- requisição HTTP assíncrona;
- conversão de PNG para GeoTIFF.

Essa separação evita duplicar a lógica de WMS entre os períodos.

### `configuracoes.py`

Armazena constantes operacionais:

- URL do WMS;
- nomes de camadas;
- CRS de entrada e saída;
- tamanho das imagens;
- número de workers;
- timeout e retentativas;
- URL do shapefile 2012.

### `utils/manifesto.py`

Grava um CSV de auditoria com o resultado de cada amostra no pipeline `2019-2020`.

O manifesto registra:

- número da amostra;
- código do imóvel;
- coordenadas originais;
- BBOX calculado;
- status do satélite;
- status do uso do solo;
- timestamp.

### `analisa_img_12_15.py`

Analisa cobertura das imagens segmentadas de `2012-2015`, classificando-as como completas ou incompletas com base em pixels vazios.

Observação técnica: este módulo ainda assume imagens RGB e nomes antigos de arquivo. Na branch `extrator-sem-rgb.py`, as máscaras são salvas como 1 banda e com nome `amostra_N.tif`, então esse módulo precisa ser ajustado para refletir o novo formato.

## Fluxo de Dados

### Entrada

A entrada é um CSV com coordenadas:

```csv
cod_imovel;x;y
ES-...;317411.43075053697;7898046.959248656
```

As coordenadas estão em `EPSG:31984`, um sistema UTM em metros.

### Cálculo do Recorte

Para cada ponto, o projeto cria um quadrado ao redor da coordenada. O parâmetro `buffer_metros` representa metade do lado do quadrado.

Com `buffer_metros = 1024`, o recorte cobre aproximadamente:

```text
2048m x 2048m
```

O BBOX é calculado em UTM e depois convertido para latitude/longitude:

```python
xmin_utm = x - buffer_metros
ymin_utm = y - buffer_metros
xmax_utm = x + buffer_metros
ymax_utm = y + buffer_metros
```

### Consulta WMS

O BBOX convertido é usado na requisição WMS. Como o projeto usa WMS `1.3.0` com `EPSG:4326`, a ordem do BBOX é invertida para `lat,lon`:

```python
bbox_str = f"{miny_lat},{minx_lon},{maxy_lat},{maxx_lon}"
```

Esse detalhe é importante: errar a ordem dos eixos em WMS 1.3.0 costuma gerar imagem vazia ou recorte incorreto.

### Persistência

As saídas são arquivos GeoTIFF em disco:

```text
pasta_saida/
  imagens satelites/
    amostra_1.tif
  imagens segmentadas/
    amostra_1.tif
```

Os GeoTIFFs recebem:

- CRS `EPSG:4326`;
- transformada espacial calculada a partir do BBOX;
- compressão LZW;
- tipo `uint8`.

## Pipeline 2019-2020

O pipeline `2019-2020` é totalmente baseado em WMS.

Para cada amostra:

1. Calcula BBOX.
2. Baixa satélite via WMS.
3. Baixa uso do solo via WMS.
4. Salva os dois como GeoTIFF.
5. Converte o uso do solo de RGB para máscara de IDs.
6. Registra resultado no manifesto.

O processamento é concorrente:

```python
semaforo = asyncio.Semaphore(cfg["workers_paralelos"])
```

Cada amostra respeita o semáforo:

```python
async with semaforo:
    ...
```

Isso evita sobrecarregar o servidor WMS e controla uso de rede.

### Conversão RGB para ID

O WMS de uso do solo retorna uma imagem renderizada por cores. A branch sem RGB converte essas cores em IDs estáveis.

O mapeamento conceitual é:

```text
RGB da classe -> ID numérico da classe
```

Exemplo:

```python
RGB_PARA_ID = {
    cor: CLASSES_IDS[nome]
    for nome, cor in CORES_CLASSES_RGB.items()
}
```

Depois, cada pixel é comparado com as cores conhecidas:

```python
for rgb, classe_id in RGB_PARA_ID.items():
    r, g, b = rgb
    mascara = (dados[0] == r) & (dados[1] == g) & (dados[2] == b)
    ids_array[mascara] = classe_id
```

O resultado é gravado como GeoTIFF de 1 banda:

```python
perfil.update(
    count=1,
    dtype="uint8",
    photometric="MINISBLACK"
)
```

## Pipeline 2012-2015

O pipeline `2012-2015` combina WMS com processamento vetorial local.

O satélite vem do WMS, mas o uso do solo não é baixado como imagem. Ele é produzido a partir de shapefile.

Fluxo:

1. Baixa ZIP do shapefile.
2. Extrai o arquivo `.shp`.
3. Lê o shapefile com GeoPandas.
4. Reprojeta para `EPSG:4326`.
5. Para cada ponto:
   - calcula BBOX;
   - recorta geometrias dentro do BBOX;
   - baixa satélite via WMS;
   - rasteriza geometrias de uso do solo;
   - grava máscara de 1 banda.

### Rasterização

Rasterizar é converter geometrias vetoriais, como polígonos, em uma matriz de pixels.

No projeto, cada polígono de uso do solo vira pixels com um ID de classe:

```python
ids_array = rasterize(
    shapes=shapes,
    out_shape=(altura, largura),
    transform=transform,
    fill=0,
    dtype="uint8",
)
```

O `fill=0` representa ausência de classe ou área sem cobertura.

### Normalização de Classes

O shapefile 2012 pode usar nomes e códigos diferentes dos usados no WMS 2019-2020. A branch cria uma tabela comum de IDs:

```python
CLASSES_IDS = {
    "Afloramento Rochoso": 1,
    "Área Edificada": 2,
    "Brejo": 3,
    ...
    "Solo Exposto": 25,
}
```

Também há aliases para nomes antigos do shapefile:

```python
"Reflorestamento - Eucalipto": 21,
"Cultivo Agrícola - Coco-Da-Baía": 9,
```

Essa decisão torna os outputs de `2012-2015` e `2019-2020` comparáveis.

## Regras de Negócio

### Entrada de Dados

Cada linha do CSV representa uma amostra. O campo `cod_imovel` é usado para rastreabilidade, enquanto `x` e `y` definem o centro do recorte.

O pipeline não consulta o CAR diretamente. Ele depende do CSV já preparado.

### Tamanho da Amostra

O tamanho da área extraída é definido pelo buffer. A configuração padrão é:

```python
"buffer_metros": 1024,
"largura_pixels": 1024,
"altura_pixels": 1024,
```

Isso gera uma imagem de `1024 x 1024` pixels cobrindo um quadrado de aproximadamente `2048 x 2048` metros.

### Formato das Imagens

As imagens de satélite são RGB, com 3 bandas.

As imagens segmentadas na branch sem RGB devem ser máscaras de 1 banda:

- `0`: sem classe / vazio;
- `1..25`: classes de uso do solo.

Essa escolha é melhor para machine learning e análise raster, porque evita depender de cores como representação semântica.

### Persistência em Disco

O sistema persiste tudo em arquivos locais. Não há banco.

Principais artefatos:

- GeoTIFFs de satélite;
- GeoTIFFs segmentados;
- manifesto CSV;
- logs;
- relatórios de cobertura para 2012.

### Tratamento de Falhas

No WMS, falhas de rede são tratadas com retentativas:

```python
for numero_tentativa in range(1, tentativas + 1):
    try:
        ...
    except (aiohttp.ClientError, RuntimeError) as erro:
        ...
```

Se uma imagem falha, a amostra recebe status de erro e o pipeline continua.

## Conceitos Técnicos Importantes

### Buffer

Buffer é a distância, em metros, aplicada ao redor da coordenada central para formar o recorte.

No projeto, o buffer não cria uma geometria circular. Ele define um quadrado:

```text
x - buffer, y - buffer, x + buffer, y + buffer
```

Impacto:

- controla a área geográfica extraída;
- afeta o nível de detalhe espacial;
- influencia tempo de download e tamanho do arquivo.

### BBOX

BBOX é o retângulo mínimo usado para solicitar ou processar uma área geográfica.

O projeto usa BBOX para:

- consultar WMS;
- criar a transformada espacial do GeoTIFF;
- recortar geometrias do shapefile;
- garantir alinhamento entre satélite e máscara.

### CRS

CRS define o sistema de coordenadas.

O projeto usa:

- `EPSG:31984` na entrada do CSV;
- `EPSG:4326` nas requisições WMS e nos GeoTIFFs gerados.

Essa conversão é estrutural. Sem ela, o WMS receberia coordenadas incompatíveis.

### Raster

Raster é uma matriz de pixels com significado espacial. No projeto, tanto imagens de satélite quanto máscaras de uso do solo são rasters.

Cada GeoTIFF contém:

- pixels;
- CRS;
- transformada espacial;
- metadados de dimensão e tipo.

### Bandas

Bandas são camadas de valores por pixel.

No projeto:

- satélite: 3 bandas RGB;
- máscara segmentada: 1 banda com ID de classe.

Essa diferença é relevante porque algoritmos de visão computacional geralmente consomem imagem e máscara com estruturas diferentes.

### Concorrência Assíncrona

O pipeline `2019-2020` usa async porque é limitado por rede. Enquanto uma requisição WMS aguarda resposta, outra pode ser executada.

Impacto:

- reduz tempo total de download;
- mantém controle de carga com semáforo;
- evita criar excesso de threads.

### Cache

O projeto usa cache simples em memória para:

- conexão WMS;
- transformadores de coordenadas.

Exemplo:

```python
if srid_entrada not in _transformador_cache:
    _transformador_cache[srid_entrada] = Transformer.from_crs(...)
```

Impacto:

- menos overhead por amostra;
- código mais eficiente em lotes grandes.

### Tiles

Tiles não são usados diretamente. O projeto solicita imagens completas por BBOX usando WMS `GetMap`.

Trade-off:

- mais simples de implementar;
- cada amostra vira uma chamada direta por recorte;
- menos controle fino sobre cache espacial quando comparado a tiles XYZ/WMTS.

### STAC

STAC não é usado. Não há busca por cenas, assets, datas ou coleções em catálogo STAC.

O acesso aos dados é direto:

- WMS para imagens renderizadas;
- URL fixa para shapefile 2012.

### NDVI

NDVI não é calculado. O projeto não trabalha com bandas NIR/vermelho separadas nem com índices espectrais.

As imagens de satélite baixadas via WMS já vêm renderizadas como RGB.

## Decisões Técnicas

### Uso de WMS em vez de download bruto de cenas

O projeto usa WMS porque o objetivo é obter recortes prontos e georreferenciados por área, não processar cenas orbitais completas.

Vantagens:

- integração simples;
- recorte direto por BBOX;
- menor volume de dados;
- não exige catálogo de cenas.

Limitações:

- depende da disponibilidade do servidor WMS;
- retorna imagem renderizada, não bandas científicas brutas;
- estilo/cor do servidor pode afetar a conversão RGB para ID.

### Máscaras de 1 banda em vez de RGB

A branch `extrator-sem-rgb.py` muda a representação de uso do solo para IDs.

Vantagens:

- formato mais adequado para segmentação semântica;
- classes ficam explícitas numericamente;
- reduz ambiguidade em comparação com cores;
- aproxima os outputs de 2012 e 2020.

Trade-off:

- a conversão 2019-2020 depende das cores exatas retornadas pelo WMS;
- mudanças de estilo no servidor podem quebrar o mapeamento;
- visualização humana direta fica menos intuitiva.

### Shapefile local para 2012-2015

O uso do solo `2012-2015` é produzido por rasterização local do shapefile, em vez de WMS.

Vantagens:

- maior controle sobre IDs de classe;
- saída consistente com o recorte;
- não depende de estilo WMS para a máscara.

Limitações:

- download inicial grande;
- processamento mais pesado em CPU/memória;
- depende da estrutura de colunas do shapefile.

### GeoTIFF como formato de saída

GeoTIFF foi escolhido porque carrega pixels e georreferenciamento no mesmo arquivo.

Vantagens:

- compatível com GIS;
- preserva CRS e transformada;
- adequado para pipelines raster e machine learning geoespacial.

Trade-off:

- arquivos maiores que PNG/JPEG;
- requer bibliotecas geoespaciais para manipulação correta.

### GUI desktop e execução via CLI/script

A GUI facilita operação manual por usuários que precisam selecionar arquivos e pastas. Ao mesmo tempo, os pipelines principais estão implementados como funções Python (`processar_ano_2012` e `processar_ano_2019_2020`), então a lógica não depende exclusivamente da interface gráfica e pode ser acionada via terminal/script.

Na arquitetura, a GUI atua como camada de entrada e orquestração visual. A execução real fica nas funções de processamento.

Trade-off:

- mantém uma interface simples para uso manual;
- permite reaproveitar a lógica em execução por terminal/script;
- ainda concentra interface e orquestração no mesmo arquivo.

## Resumo Técnico

O sistema é um pipeline Python operável por interface desktop e por execução via terminal/script, que transforma coordenadas tabulares em um dataset geoespacial raster. A arquitetura combina WMS para imagens renderizadas, GeoPandas para dados vetoriais, RasterIO para persistência georreferenciada e asyncio para acelerar downloads.

A principal decisão técnica da branch é representar uso do solo como máscara categórica de 1 banda. Isso torna o dataset mais adequado para processamento computacional, mas exige cuidado com a conversão das cores do WMS e com módulos herdados da versão RGB.
