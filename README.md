# IntegraCar — Pipeline Multi-Satélite de Extração de Imagens

Pipeline automatizado em Python para download de imagens geoespaciais a partir de coordenadas UTM. Suporta múltiplos satélites via **WMS** e **STAC**, com interface **CLI** e **GUI (Tkinter)**.

Para cada coordenada do CSV, o pipeline:

1. Busca a melhor cena disponível (menor cobertura de nuvens)
2. Baixa as bandas em paralelo (asyncio)
3. Gera GeoTIFF georreferenciado
4. Opcionalmente baixa camada de uso do solo (GeoBases ES)

---

## Satélites Suportados

| Satélite | Protocolo | Resolução | Bandas | Fonte |
|----------|-----------|-----------|--------|-------|
| **KOMPSAT** | WMS | 0.5m | RGB | GeoBases ES |
| **Sentinel-2** | STAC | 10-20m | B02-B04, B08 (NIR), B11/B12 (SWIR) | Planetary Computer |
| **Landsat 8/9** | STAC | 30-100m | RGB, NIR, SWIR, **TIR** | Planetary Computer |
| **CBERS-4A** | STAC | 2m | BAND1-4 (RGB + NIR) | INPE/BDC |

---

## Instalação

```bash
git clone https://github.com/arthurvtl/car-imagens-downloader.git
cd projeto-automacao

python3 -m venv venv
source venv/bin/activate          # macOS / Linux
# venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

---

## Como Usar

### CLI (Principal)

```bash
# KOMPSAT (legado) + camada segmentada
python main.py run --csv coordenadas_treino_amostra.csv --satellite kompsat --layer true

# Sentinel-2 com filtro de nuvens
python main.py run --csv coords.csv --satellite sentinel --cloud 20 -o saida_sentinel

# Landsat com banda termal (TIR)
python main.py run --csv coords.csv --satellite landsat --cloud 15

# CBERS-4A (satélite brasileiro, 2m)
python main.py run --csv coords.csv --satellite cbers --cloud 30

# Teste rápido (5 imagens)
python main.py run --csv coords.csv --satellite sentinel --limit 5

# Listar satélites
python main.py list-satellites

# Ajuda
python main.py run --help
```

### GUI (Tkinter)

```bash
python main.py gui
```

A interface gráfica permite selecionar CSV, pasta de saída, satélite, configurar parâmetros e acompanhar o progresso em tempo real.

### Pipeline Legado

O `extrator.py` original permanece funcional para compatibilidade:

```bash
python extrator.py    # Abre a GUI legada (2012 / 2019-2020)
```

---

## Parâmetros CLI

| Parâmetro | Obrigatório | Descrição | Padrão |
|-----------|:-----------:|-----------|--------|
| `--csv` | Sim | CSV com colunas `cod_imovel`, `x`, `y` (sep: `;`) | — |
| `--satellite`, `-s` | — | `kompsat`, `sentinel`, `landsat` ou `cbers` | `kompsat` |
| `--output`, `-o` | — | Pasta de saída | `saida` |
| `--cloud` | — | Cobertura máxima de nuvens (%) | `20` |
| `--layer` | — | Baixar camada segmentada: `true`/`false` | `false` |
| `--buffer` | — | Metade do recorte em metros | `1024` |
| `--width` | — | Largura em pixels | `1024` |
| `--height` | — | Altura em pixels | `1024` |
| `--workers` | — | Downloads simultâneos | `4` |
| `--limit` | — | Limitar a N coordenadas | todas |
| `--date-start` | — | Data inicial (YYYY-MM-DD) | `2023-01-01` |
| `--date-end` | — | Data final (YYYY-MM-DD) | `2024-12-31` |
| `--config` | — | config.yaml alternativo | `config.yaml` |

---

## Estrutura de Saída

```
saida/
├── SATELITE/
│   ├── amostra_1.tif          # GeoTIFF do satélite escolhido
│   ├── amostra_2.tif
│   └── ...
└── SEGMENTADO/                 # Apenas se --layer true
    ├── amostra_1.tif          # Uso do solo (GeoBases ES)
    └── ...

artifacts/
└── dataset_manifesto.csv       # Registro de cada download

logs/
└── execucao.log                # Log detalhado
```

---

## Formato do CSV de Entrada

Separador: **ponto-e-vírgula** (`;`)

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `cod_imovel` | string | Código do imóvel no CAR |
| `x` | float | Coordenada X em metros (EPSG:31984 — UTM 24S) |
| `y` | float | Coordenada Y em metros (EPSG:31984) |

---

## Fluxo do Pipeline

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

### Detalhes Técnicos por Etapa

**1. Leitura do CSV** — `pandas` lê o arquivo e aplica o limite (`--limit`).

**2. Conversão de coordenadas** — `pyproj.Transformer` converte UTM (EPSG:31984) para lat/lon (EPSG:4326). O transformer é cacheado para performance.

**3. Busca de imagens** —
- **KOMPSAT (WMS)**: não há busca real; a camada WMS é fixa.
- **STAC (Sentinel/Landsat/CBERS)**: `pystac-client` busca items por bbox, intervalo de datas e cobertura de nuvens. `planetary-computer` assina URLs quando necessário.

**4. Download paralelo** — `asyncio` + `aiohttp` com `Semaphore(N workers)`. Para STAC, o `rasterio` lê janelas de COGs remotos via HTTP range requests em thread executor (`run_in_executor`), baixando apenas os pixels necessários.

**5. Conversão para GeoTIFF** — `Pillow` decodifica PNG (WMS) ou `numpy` empilha bandas (STAC). `rasterio` escreve o GeoTIFF georreferenciado com CRS, transform afim e compressão LZW. Executado em thread separada para não bloquear o event loop.

**6. Manifesto** — `csv.DictWriter` registra cada download em tempo real (modo append). Permite retomada idempotente.

---

## Arquitetura do Projeto

```
projeto-automacao/
├── main.py                     # Ponto de entrada (CLI + GUI)
├── config.yaml                 # Configuração centralizada
├── requirements.txt            # Dependências Python
├── COMO_EXECUTAR.md            # Guia passo a passo
├── HELP.md                     # Referência completa
│
├── src/                        # Arquitetura modular
│   ├── core/
│   │   ├── config.py           # PipelineConfig (YAML → dataclass)
│   │   ├── pipeline.py         # Orquestrador assíncrono
│   │   └── manifest.py         # Manifesto CSV
│   ├── satellites/
│   │   ├── base.py             # BaseSatellite (contrato abstrato)
│   │   ├── kompsat.py          # KompsatProvider (WMS adapter)
│   │   ├── sentinel.py         # SentinelProvider (STAC)
│   │   ├── landsat.py          # LandsatProvider (STAC)
│   │   ├── cbers.py            # CbersProvider (STAC + fallback)
│   │   └── registry.py         # Factory de provedores
│   ├── stac/
│   │   └── client.py           # Wrapper pystac-client + Planetary Computer
│   ├── processing/
│   │   ├── coordinates.py      # Conversão UTM → lat/lon
│   │   ├── geotiff.py          # Escrita de GeoTIFF
│   │   └── raster.py           # Leitura COG, empilhamento
│   ├── cli/
│   │   └── commands.py         # CLI (argparse)
│   └── gui/
│       └── app.py              # GUI (Tkinter)
│
├── extrator.py                 # Pipeline legado (preservado)
├── configuracoes.py            # Config legada (preservada)
├── utils/                      # Módulos legados (preservados)
│   ├── wms.py
│   └── manifesto.py
│
└── docs/
    ├── architecture.md         # Arquitetura detalhada
    ├── libraries.md            # Referência de bibliotecas
    └── satellites.md           # Guia técnico dos satélites
```

---

## Tecnologias

| Biblioteca | Papel |
|------------|-------|
| `asyncio` + `aiohttp` | Downloads HTTP assíncronos paralelos |
| `pystac-client` | Busca em catálogos STAC |
| `planetary-computer` | Assinatura de assets (Planetary Computer) |
| `rasterio` | Leitura/escrita GeoTIFF, COG windowed reads |
| `numpy` | Manipulação de arrays raster |
| `pyproj` | Conversão de coordenadas (UTM → lat/lon) |
| `pandas` | Leitura de CSV |
| `Pillow` | Decodificação de PNG (WMS) |
| `OWSLib` | Conexão/validação WMS |
| `tqdm` | Barra de progresso |
| `PyYAML` | Configuração YAML |
| `tkinter` | Interface gráfica |

---

## Documentação Adicional

- [`COMO_EXECUTAR.md`](COMO_EXECUTAR.md) — Guia passo a passo detalhado
- [`HELP.md`](HELP.md) — Referência completa (satélites, conceitos, STAC, erros)
- [`docs/architecture.md`](docs/architecture.md) — Arquitetura e padrões de projeto
- [`docs/libraries.md`](docs/libraries.md) — Mapa de dependências
- [`docs/satellites.md`](docs/satellites.md) — Especificações técnicas dos satélites
