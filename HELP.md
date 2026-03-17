# IntegraCar — Pipeline Multi-Satélite: Guia Completo

---

## 1. VISÃO GERAL

O IntegraCar é um pipeline em Python para download automatizado de imagens
geoespaciais a partir de coordenadas UTM. Originalmente desenvolvido para
KOMPSAT (GeoBases ES via WMS), o sistema foi evoluído para suportar múltiplos
satélites via protocolo STAC (SpatioTemporal Asset Catalog).

### Satélites Suportados

| Satélite   | Fonte           | Protocolo | Bandas Disponíveis                  |
|------------|-----------------|-----------|-------------------------------------|
| KOMPSAT    | GeoBases ES     | WMS       | RGB (0.5m)                          |
| Sentinel-2 | Planetary Comp. | STAC      | B02-B04 (10m), B08 NIR, B11/B12    |
| Landsat    | Planetary Comp. | STAC      | RGB (30m), NIR, SWIR, TIR (100m)   |
| CBERS-4A   | INPE/BDC        | STAC      | BAND1-4 (2m)                        |

### Funcionalidades

- Download paralelo assíncrono (asyncio + aiohttp)
- Busca inteligente por menor cobertura de nuvens
- Camada segmentada de uso do solo (opcional, GeoBases ES)
- Saída em GeoTIFF georreferenciado
- Interface CLI e GUI (Tkinter)
- Manifesto CSV para rastreabilidade do dataset

---

## 2. COMO EXECUTAR

### Pré-requisitos

```bash
python -m venv venv
source venv/bin/activate       # Linux/macOS
pip install -r requirements.txt
```

### CLI (Principal)

```bash
# Download com KOMPSAT (legado)
python main.py run --csv coordenadas_treino_amostra.csv --satellite kompsat

# Download com Sentinel-2 + camada segmentada
python main.py run --csv coords.csv --satellite sentinel --cloud 20 --layer true

# Download com Landsat incluindo TIR
python main.py run --csv coords.csv --satellite landsat --cloud 15 -o saida_landsat

# Listar satélites disponíveis
python main.py list-satellites

# Parâmetros avançados
python main.py run \
  --csv coords.csv \
  --satellite sentinel \
  --cloud 20 \
  --layer true \
  --buffer 512 \
  --width 512 \
  --height 512 \
  --workers 8 \
  --limit 100 \
  --date-start 2023-06-01 \
  --date-end 2024-01-01
```

### GUI (Interface Gráfica)

```bash
python main.py gui
```

A interface permite:
- Selecionar CSV e pasta de saída
- Escolher satélite via dropdown
- Ativar/desativar camada segmentada via checkbox
- Ajustar parâmetros (cloud cover, buffer, dimensões)
- Acompanhar progresso e log em tempo real

### Pipeline Legado (Compatibilidade)

O arquivo `extrator.py` original permanece funcional:

```bash
python extrator.py  # Abre GUI legada
```

---

## 3. FLUXO DO PIPELINE

```
CSV de Coordenadas (UTM)
         │
         ▼
 ┌─────────────────┐
 │ Calcular BBOX   │  pyproj: UTM → lat/lon
 │ (EPSG:4326)     │
 └────────┬────────┘
          │
          ▼
 ┌─────────────────┐
 │ Buscar Imagens  │  WMS (KOMPSAT) ou STAC (Sentinel/Landsat/CBERS)
 └────────┬────────┘
          │
          ▼
 ┌─────────────────┐
 │ Selecionar      │  Menor cobertura de nuvens
 │ Melhor Cena     │
 └────────┬────────┘
          │
          ▼
 ┌─────────────────┐
 │ Download        │  aiohttp (WMS) ou rasterio COG window (STAC)
 │ Paralelo        │  asyncio.Semaphore controla concorrência
 └────────┬────────┘
          │
    ┌─────┴─────┐
    ▼           ▼
 Satélite   Segmentada
 (GeoTIFF)  (Opcional)
    │           │
    └─────┬─────┘
          ▼
 ┌─────────────────┐
 │ Registrar no    │  dataset_manifesto.csv
 │ Manifesto       │
 └─────────────────┘
```

---

## 4. SATÉLITES — Detalhes Técnicos

### KOMPSAT-3/3A

- **Fonte**: GeoBases ES (WMS)
- **Bandas**: RGB (Red, Green, Blue)
- **Resolução**: 0.5 metros
- **Cobertura**: Espírito Santo (Brasil)
- **Uso ideal**: Alta resolução espacial, análise visual detalhada,
  mapeamento urbano, monitoramento de propriedades rurais
- **Protocolo**: WMS GetMap (legado)
- **Nota**: Sem busca temporal — sempre retorna o mosaico disponível

### Sentinel-2 (Level-2A)

- **Fonte**: Microsoft Planetary Computer (STAC)
- **Bandas**:
  - B02 (Blue, 490nm, 10m)
  - B03 (Green, 560nm, 10m)
  - B04 (Red, 665nm, 10m)
  - B08 (NIR, 842nm, 10m)
  - B11 (SWIR-1, 1610nm, 20m)
  - B12 (SWIR-2, 2190nm, 20m)
- **Resolução**: 10-20 metros
- **Revisita**: ~5 dias (constelação de 2 satélites)
- **Uso ideal**: Monitoramento agrícola (NDVI), análise de vegetação,
  detecção de queimadas, mapeamento de uso do solo

### Landsat 8/9 (Collection 2 Level-2)

- **Fonte**: Microsoft Planetary Computer (STAC)
- **Bandas**:
  - Blue (482nm, 30m)
  - Green (562nm, 30m)
  - Red (655nm, 30m)
  - NIR (865nm, 30m)
  - SWIR-1 (1609nm, 30m)
  - SWIR-2 (2201nm, 30m)
  - **TIR (10895nm, 100m)** — banda termal
- **Resolução**: 30-100 metros
- **Revisita**: ~8 dias (2 satélites combinados)
- **Uso ideal**: Séries temporais longas (dados desde 1972),
  análise termal (ilhas de calor), estudos climáticos

### CBERS-4A (WPM)

- **Fonte**: INPE/BDC (STAC brasileiro)
- **Bandas**:
  - BAND1 (Blue, 485nm, 2m)
  - BAND2 (Green, 555nm, 2m)
  - BAND3 (Red, 660nm, 2m)
  - BAND4 (NIR, 830nm, 2m)
- **Resolução**: 2 metros
- **Uso ideal**: Alta resolução brasileira, monitoramento de
  desmatamento, mapeamento cadastral

---

## 5. CONCEITOS FUNDAMENTAIS

### NIR (Near Infrared — Infravermelho Próximo)

Faixa espectral de ~700-1100nm. Vegetação saudável reflete fortemente
no NIR (a clorofila absorve luz visível mas reflete NIR). Essencial
para cálculos de NDVI e detecção de estresse hídrico.

### SWIR (Shortwave Infrared — Infravermelho de Ondas Curtas)

Faixa de ~1100-2500nm. Sensível ao conteúdo de água na vegetação e
no solo. Usado para:
- Diferenciação de tipos de solo
- Detecção de queimadas ativas
- Mapeamento de minerais

### TIR (Thermal Infrared — Infravermelho Termal)

Faixa de ~8000-14000nm. Mede temperatura de superfície. Disponível
no Landsat (banda lwir11). Usado para:
- Ilhas de calor urbanas
- Monitoramento de incêndios
- Estudos de evapotranspiração

### NDVI (Normalized Difference Vegetation Index)

```
NDVI = (NIR - RED) / (NIR + RED)
```

- Valores: -1 a +1
- Vegetação densa: 0.6 a 0.9
- Solo exposto: 0.1 a 0.2
- Água: negativo

Para calcular NDVI com Sentinel-2: use bandas B08 (NIR) e B04 (Red).

---

## 6. STAC (SpatioTemporal Asset Catalog)

### O que é

STAC é um padrão aberto para descrever dados geoespaciais de forma que
sejam facilmente buscáveis e acessíveis. Pense nele como um "catálogo
de biblioteca" para imagens de satélite.

### Componentes

- **Catalog**: ponto de entrada do catálogo
- **Collection**: grupo de items com características comuns (ex: Sentinel-2 L2A)
- **Item**: uma cena/observação específica com metadados (data, bbox, cloud cover)
- **Asset**: arquivo real dentro de um item (ex: banda B04, thumbnail)

### Como Funciona no IntegraCar

```
1. Conecta ao catálogo STAC (Planetary Computer ou INPE)
2. Busca items que intersectam o bbox da coordenada
3. Filtra por data e cobertura de nuvens
4. Seleciona o melhor item
5. Obtém URLs dos assets (bandas)
6. Lê janelas dos COG (Cloud Optimized GeoTIFF) remotos
7. Só baixa os pixels necessários (eficiente!)
```

### Cloud Optimized GeoTIFF (COG)

COGs são GeoTIFFs otimizados para acesso via HTTP range requests.
Permitem ler apenas uma porção do arquivo sem baixar tudo.
O rasterio usa internamente o GDAL com `/vsicurl/` para isso.

---

## 7. ESTRUTURA DE SAÍDA

```
saida/
├── SATELITE/
│   ├── amostra_1.tif     # GeoTIFF do satélite escolhido
│   ├── amostra_2.tif
│   └── ...
├── SEGMENTADO/            # Apenas se --layer true
│   ├── amostra_1.tif     # Uso do solo (GeoBases)
│   └── ...
artifacts/
├── dataset_manifesto.csv  # Rastreabilidade completa
logs/
├── execucao.log           # Log detalhado
```

### Manifesto CSV

Colunas: `numero_amostra`, `cod_imovel`, `x`, `y`, `bbox_*`,
`satelite`, `status_satelite`, `status_segmentada`, `item_id`,
`cloud_cover`, `data_download`

---

## 8. ERROS COMUNS

| Erro | Causa | Solução |
|------|-------|---------|
| `Satélite 'xxx' não suportado` | Nome incorreto | Use `python main.py list-satellites` |
| `Nenhuma cena encontrada` | Bbox fora da cobertura ou cloud > max | Aumente `--cloud` ou mude datas |
| `planetary-computer não instalado` | Dependência ausente | `pip install planetary-computer` |
| `GDAL error` ao ler COG | Versão antiga do rasterio/GDAL | `pip install --upgrade rasterio` |
| `WMS retornou erro` | Servidor GeoBases offline | Tente novamente mais tarde |
| Timeout em download | Rede lenta ou servidor sobrecarregado | Aumente `timeout_requisicao` em config.yaml |
| `CSV deve conter colunas 'x' e 'y'` | CSV incorreto | Verifique separador (;) e colunas |

---

## 9. PERFORMANCE

### Estratégia de Paralelismo

- **I/O-bound** (downloads): `asyncio` + `aiohttp` com `Semaphore`
- **CPU-bound** (GeoTIFF, rasterio): `ThreadPoolExecutor` via `loop.run_in_executor`
- **STAC COG reads**: Thread executor (rasterio é síncrono)

### Ajustes Recomendados

| Parâmetro | Padrão | Recomendação |
|-----------|--------|--------------|
| `workers_paralelos` | 4 | 4-8 para internet estável |
| `timeout_requisicao` | 60 | 120 para conexões lentas |
| `tentativas_por_imagem` | 3 | 5 para servidores instáveis |
| `buffer_metros` | 1024 | Menor buffer = downloads mais rápidos |
| `largura_pixels` | 1024 | 512 para testes rápidos |

### WMS vs STAC — Performance

- **WMS** (KOMPSAT): download direto do PNG, mais rápido por imagem
- **STAC** (Sentinel/Landsat): leitura de COG via HTTP range requests,
  usa mais round-trips mas baixa apenas os pixels necessários

---

## 10. EXEMPLOS REAIS

### Exemplo 1: Monitoramento Agrícola com Sentinel-2

```bash
python main.py run \
  --csv fazendas.csv \
  --satellite sentinel \
  --cloud 10 \
  --buffer 2048 \
  --date-start 2024-03-01 \
  --date-end 2024-09-30
```

Baixa imagens RGB de Sentinel-2 com pouca nuvem durante a safra.

### Exemplo 2: Análise Termal com Landsat

```bash
python main.py run \
  --csv cidades.csv \
  --satellite landsat \
  --cloud 15 \
  --buffer 5000 \
  --width 512 \
  --height 512
```

Inclui banda TIR (lwir11) para análise de ilhas de calor.

### Exemplo 3: Pipeline Completo KOMPSAT + Segmentada

```bash
python main.py run \
  --csv coordenadas_treino_amostra.csv \
  --satellite kompsat \
  --layer true \
  --buffer 1024 \
  -o dataset_treino
```

Replica o comportamento original do pipeline legado.

### Exemplo 4: Alta Resolução com CBERS-4A

```bash
python main.py run \
  --csv pontos_amazonia.csv \
  --satellite cbers \
  --cloud 30 \
  --date-start 2023-01-01 \
  --date-end 2024-12-31
```

Usa o satélite brasileiro CBERS-4A com resolução de 2m.
