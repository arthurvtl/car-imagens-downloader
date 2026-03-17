# Bibliotecas e Dependências

## Dependências Principais

### asyncio + aiohttp
**Papel**: Downloads HTTP assíncronos paralelos.
- `asyncio.Semaphore` controla o número de workers simultâneos
- `aiohttp.ClientSession` gerencia o pool de conexões
- `aiohttp.TCPConnector` limita conexões por host

### pystac-client
**Papel**: Busca em catálogos STAC (Sentinel, Landsat, CBERS).
- `Client.open()` conecta ao catálogo
- `catalog.search()` busca items por bbox, datas, cloud cover
- Retorna objetos `pystac.Item` com metadados e links para assets

### planetary-computer
**Papel**: Autenticação e assinatura de assets do Microsoft Planetary Computer.
- `planetary_computer.sign_inplace` assina URLs de assets com tokens SAS
- Necessário para acessar COGs do Sentinel-2 e Landsat no PC
- Transparente: aplicado como `modifier` no pystac-client

### rasterio
**Papel**: Leitura/escrita de dados raster geoespaciais.
- Escrita de GeoTIFF georreferenciados
- Leitura de janelas (windows) de COG remotos via `/vsicurl/`
- Reprojeção e reamostragem de dados raster
- Baseado em GDAL internamente

### numpy
**Papel**: Manipulação de arrays numéricos (dados raster).
- Empilhamento de bandas (`np.stack`)
- Normalização de reflectância para uint8
- Operações vetorizadas em matrizes de pixels

### pyproj
**Papel**: Conversão entre sistemas de coordenadas.
- UTM (EPSG:31984) → lat/lon (EPSG:4326)
- `Transformer` com cache para performance
- Usado no cálculo de bounding boxes

### pandas
**Papel**: Leitura e manipulação do CSV de coordenadas.
- `pd.read_csv` com separador `;`
- Filtragem de amostras já processadas
- Iteração sobre coordenadas

### Pillow (PIL)
**Papel**: Decodificação de imagens PNG recebidas do WMS.
- Converte bytes PNG → array numpy (H, W, C)
- Usado apenas no fluxo WMS (KOMPSAT)

### OWSLib
**Papel**: Conexão e validação de serviços WMS.
- `WebMapService` para conectar ao GeoBases ES
- Validação de camadas disponíveis
- Usado apenas no fluxo legado

### tqdm
**Papel**: Barra de progresso no terminal.
- Mostra progresso por amostra processada
- Funciona com `asyncio.as_completed()`

### geopandas + shapely
**Papel**: Processamento de shapefiles (fluxo 2012).
- Leitura de shapefiles de uso do solo
- Operações espaciais (intersecção, reprojeção)
- Rasterização de geometrias

### PyYAML
**Papel**: Leitura do arquivo de configuração `config.yaml`.
- `yaml.safe_load()` converte YAML → dicionário Python
- Configuração centralizada para todos os componentes

## Diagrama de Dependências

```
main.py
  └── src/cli/commands.py
        ├── src/core/config.py ← PyYAML
        ├── src/core/pipeline.py
        │     ├── asyncio + aiohttp
        │     ├── pandas (CSV)
        │     ├── tqdm (progresso)
        │     ├── src/satellites/registry.py
        │     │     ├── KompsatProvider ← OWSLib, Pillow
        │     │     ├── SentinelProvider ← pystac-client, planetary-computer
        │     │     ├── LandsatProvider ← pystac-client, planetary-computer
        │     │     └── CbersProvider ← pystac-client
        │     ├── src/processing/coordinates.py ← pyproj
        │     ├── src/processing/geotiff.py ← rasterio, numpy, Pillow
        │     └── src/processing/raster.py ← rasterio, numpy
        └── src/gui/app.py ← tkinter
```
