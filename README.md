# 🛰️ IntegraCar — Pipeline de Extração de Imagens

## O que é este projeto?

É um pipeline automatizado que baixa imagens de satélite e mapas de uso do solo do **GeoBases do Espírito Santo** (IDE GeoBases) para propriedades rurais cadastradas no CAR (Cadastro Ambiental Rural).

Para cada propriedade listada em um arquivo CSV, o pipeline:

1. **Lê as coordenadas UTM** da propriedade
2. **Converte para latitude/longitude** (EPSG:4326)
3. **Solicita ao servidor WMS** duas imagens:
   - **SEM COR** — imagem de satélite bruta (ortofotomosaico KOMPSAT 2019-2020)
   - **COM COR** — mapa de uso do solo colorido (classificação IJSN 2019)
4. **Salva como GeoTIFF** georreferenciado com compressão LZW
5. **Registra no manifesto CSV** o resultado de cada download

---

## Arquitetura do Pipeline

```
coordenadas_treino_amostra.csv     ← entrada (coordenadas UTM + código do imóvel)
         │
         ▼
   ┌─────────────┐
   │ extrator.py  │  ← orquestrador principal (asyncio)
   └──────┬──────┘
          │
          │  Para cada amostra (até 4 em paralelo):
          │
          ├──► asyncio.gather ──► SEM COR (satélite)   ──► salvar GeoTIFF
          │                  └──► COM COR (uso solo)   ──► salvar GeoTIFF
          │
          ▼
   ┌──────────────┐
   │ utils/wms.py │  ← comunicação HTTP (aiohttp) + conversão raster
   └──────────────┘
          │
          ▼
   GeoBases WMS Server (https://ide.geobases.es.gov.br/geoserver/ows)
```

---

## Estrutura de Arquivos

```
projeto-automacao/
├── configuracoes.py                 ← todas as configurações (URLs, camadas, dimensões)
├── extrator.py                      ← script principal — orquestra o pipeline
├── coordenadas_treino_amostra.csv   ← CSV de entrada com coordenadas UTM
├── requirements.txt                 ← dependências Python
│
├── utils/
│   ├── wms.py                       ← funções de download WMS + conversão GeoTIFF
│   └── manifesto.py                 ← gerenciamento do CSV de manifesto
│
├── saida/
│   ├── SEM COR/                     ← imagens de satélite brutas (.tif)
│   └── COM COR/                     ← mapas de uso do solo coloridos (.tif)
│
├── artifacts/
│   └── dataset_manifesto.csv        ← registro de cada amostra processada
│
├── logs/
│   └── execucao.log                 ← log completo de execução
```

---

## Como Executar

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Rodar o pipeline

```bash
python extrator.py
```

O pipeline vai:

- Conectar ao GeoBases
- Ler o CSV com coordenadas
- Baixar todas as imagens em paralelo (4 amostras × 2 imagens = até 8 requisições simultâneas)
- Salvar os GeoTIFFs em `saida/SEM COR/` e `saida/COM COR/`
- Registrar tudo em `artifacts/dataset_manifesto.csv`

---

## Tecnologias Utilizadas

| Tecnologia | Uso |
|---|---|
| **asyncio + aiohttp** | Downloads assíncronos de alta performance |
| **OWSLib** | Conexão e validação do serviço WMS |
| **Pillow** | Decodificação de imagens PNG recebidas do servidor |
| **rasterio** | Criação de arquivos GeoTIFF georreferenciados |
| **pyproj** | Conversão de coordenadas UTM → lat/lon |
| **pandas** | Leitura e manipulação do CSV de entrada |
| **tqdm** | Barra de progresso no terminal |
| **numpy** | Manipulação de arrays de pixels |

---

## Fluxo de Dados Detalhado

### Entrada

O arquivo `coordenadas_treino_amostra.csv` contém colunas separadas por `;`:

- `cod_imovel` — código do imóvel no CAR
- `x` — coordenada X em metros (EPSG:31984 — UTM zona 24S)
- `y` — coordenada Y em metros (EPSG:31984)

### Processamento

1. **Conversão de coordenadas**: `(x, y)` em UTM → `(lon, lat)` em graus decimais via `pyproj`
2. **Cálculo do bbox**: cria uma caixa de 1024m × 1024m (buffer de 512m em cada direção)
3. **Requisição WMS**: envia um `GetMap` ao GeoServer pedindo uma imagem 1024×1024 pixels em PNG
4. **Conversão para GeoTIFF**: decodifica o PNG via Pillow, calcula a transformação afim, e grava com rasterio usando compressão LZW

### Saída

- `saida/SEM COR/amostra_1.tif` — GeoTIFF da imagem de satélite
- `saida/COM COR/amostra_1.tif` — GeoTIFF do mapa de uso do solo
- `artifacts/dataset_manifesto.csv` — registro com status, coordenadas e timestamp

---

## Otimizações de Performance

O pipeline usa várias técnicas para maximizar velocidade:

1. **asyncio + aiohttp** — requisições HTTP assíncronas sem overhead de threads
2. **asyncio.Semaphore** — limita a concorrência para não sobrecarregar o servidor
3. **asyncio.gather** — SEM COR e COM COR de cada amostra são baixados simultaneamente
4. **TCPConnector com pool** — reutiliza conexões TCP (keep-alive)
5. **run_in_executor** — operações CPU-bound (Pillow + rasterio) rodam em threads separadas sem bloquear o event loop
6. **Cache de transformadores** — evita recriar objetos `pyproj.Transformer` a cada chamada
7. **Cache de conexão WMS** — evita reconectar ao OWSLib a cada imagem

---

## Configuração

Todas as configurações ficam em `configuracoes.py`. Os valores mais importantes:

| Chave | Valor Padrão | Descrição |
|---|---|---|
| `workers_paralelos` | 4 | Quantas amostras são processadas ao mesmo tempo |
| `timeout_requisicao` | 60s | Timeout por requisição HTTP |
| `tentativas_por_imagem` | 3 | Retentativas em caso de falha |
| `buffer_metros` | 512 | Metade do lado do recorte (512 = quadrado de 1024m) |
| `largura_pixels` | 1024 | Resolução horizontal da imagem |
| `altura_pixels` | 1024 | Resolução vertical da imagem |
