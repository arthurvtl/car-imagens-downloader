# Arquitetura do Pipeline Multi-Satélite IntegraCar

## Visão Geral

O sistema segue uma arquitetura **modular em camadas** com separação clara entre:

1. **Interface** (CLI / GUI) — entrada do usuário
2. **Orquestração** (Pipeline) — controle de fluxo
3. **Provedores** (Satellites) — lógica específica de cada satélite
4. **Processamento** (Processing) — operações raster e geoespaciais
5. **Infraestrutura** (STAC Client, Config, Manifest) — serviços transversais

```
┌─────────────────────────────────────────┐
│           Interface (CLI / GUI)         │
├─────────────────────────────────────────┤
│           Pipeline Orquestrador         │
│         (src/core/pipeline.py)          │
├────────┬────────┬────────┬──────────────┤
│KOMPSAT │SENTINEL│LANDSAT │    CBERS     │
│ (WMS)  │ (STAC) │ (STAC) │   (STAC)    │
├────────┴────────┴────────┴──────────────┤
│         STAC Client / WMS Client        │
├─────────────────────────────────────────┤
│      Processing (GeoTIFF, Raster)       │
├─────────────────────────────────────────┤
│   Config (YAML)  │  Manifest (CSV)      │
└──────────────────┴──────────────────────┘
```

## Estrutura de Diretórios

```
projeto-automacao/
├── main.py                    # Ponto de entrada
├── config.yaml                # Configuração central
├── extrator.py                # GUI legada (preservada)
├── configuracoes.py           # Config legada (preservada)
├── src/
│   ├── core/
│   │   ├── config.py          # Carregamento YAML → dataclass
│   │   ├── pipeline.py        # Orquestrador assíncrono
│   │   └── manifest.py        # Gerenciamento do manifesto
│   ├── satellites/
│   │   ├── base.py            # BaseSatellite (contrato abstrato)
│   │   ├── kompsat.py         # KompsatProvider (WMS adapter)
│   │   ├── sentinel.py        # SentinelProvider (STAC)
│   │   ├── landsat.py         # LandsatProvider (STAC)
│   │   ├── cbers.py           # CbersProvider (STAC)
│   │   └── registry.py        # Factory + registro de provedores
│   ├── stac/
│   │   └── client.py          # Wrapper pystac-client + assinatura
│   ├── processing/
│   │   ├── coordinates.py     # Conversão UTM → lat/lon, bbox
│   │   ├── geotiff.py         # Escrita de GeoTIFF
│   │   └── raster.py          # Leitura COG, empilhamento
│   ├── cli/
│   │   └── commands.py        # Parser argparse + comandos
│   └── gui/
│       └── app.py             # Interface Tkinter
├── utils/                     # Módulos legados (preservados)
│   ├── wms.py
│   └── manifesto.py
└── docs/
    ├── architecture.md
    ├── libraries.md
    └── satellites.md
```

## Padrões de Projeto

### Strategy Pattern (Satélites)

`BaseSatellite` define o contrato. Cada provedor implementa a estratégia
específica de busca e download. O `registry.py` funciona como Factory.

### Adapter Pattern (KOMPSAT)

`KompsatProvider` adapta o protocolo WMS legado para o contrato
`BaseSatellite`, permitindo que o pipeline trate todos os satélites
uniformemente.

### Pipeline Pattern (Orquestrador)

O `pipeline.py` orquestra o fluxo: ler CSV → para cada coordenada →
buscar → selecionar → baixar → salvar → registrar.

### Observer Pattern (GUI Logging)

A GUI usa `queue.Queue` + polling para receber logs em tempo real
sem bloquear a thread principal do Tkinter.

## Estratégia de Concorrência

```
MainThread (GUI/CLI)
    │
    └── asyncio.run()
            │
            ├── Semaphore(N workers)
            │     │
            │     ├── Task: amostra_1
            │     │     ├── search (STAC/WMS)
            │     │     ├── download (aiohttp / rasterio)
            │     │     │     └── run_in_executor (ThreadPool)
            │     │     └── save GeoTIFF (ThreadPool)
            │     │
            │     ├── Task: amostra_2
            │     └── ...
            │
            └── aiohttp.ClientSession (connection pooling)
```

- **I/O-bound**: `asyncio` + `aiohttp` com `TCPConnector`
- **CPU-bound**: `loop.run_in_executor()` com `ThreadPoolExecutor`
- **STAC COG**: rasterio (síncrono) executado em thread separada
- **GUI**: Thread separada para o pipeline; `root.after()` para updates

## Extensibilidade

Para adicionar um novo satélite:

1. Criar `src/satellites/novo_sat.py` herdando `BaseSatellite`
2. Implementar `search`, `select_best_item`, `get_assets`, `download`, `get_bands`
3. Registrar em `src/satellites/registry.py` via `register_satellite()`
4. Adicionar configuração em `config.yaml → satellites`
