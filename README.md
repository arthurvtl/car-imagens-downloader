# 🛰️ IntegraCar — Pipeline de Extração de Imagens

Pipeline automatizado que baixa imagens de satélite e mapas de uso do solo do **GeoBases do Espírito Santo** para propriedades rurais cadastradas no CAR (Cadastro Ambiental Rural).

<<<<<<< HEAD
É um pipeline automatizado que baixa imagens de satélite e mapas de uso do solo do **GeoBases do Espírito Santo** (IDE GeoBases) para propriedades rurais cadastradas no CAR (Cadastro Ambiental Rural).
=======
Para cada coordenada listada em um arquivo CSV, o pipeline produz dois arquivos GeoTIFF georreferenciados:
>>>>>>> ed706eb (Atualizacoes para uso do programa)

- **SATELITE** — ortofotomosaico bruto (KOMPSAT 2019-2020)
- **SEGMENTADO** — mapa de uso e cobertura do solo (IJSN 2019)

---

<<<<<<< HEAD
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
=======
## Instalação
>>>>>>> ed706eb (Atualizacoes para uso do programa)

```bash
git clone <url-do-repositorio>
cd projeto-automacao
pip install -r requirements.txt
```

---

## Como Usar

```bash
# Forma mais simples (usa todos os defaults)
python extrator.py --csv coordenadas.csv --caminho ./saida

# Forma completa com todos os parâmetros
python extrator.py \
  --csv coordenadas_treino_amostra.csv \
  --caminho ./saida \
  --buffer 1024 \
  --largura 1024 \
  --altura 1024 \
  --qtd 1000

# Ver ajuda
python extrator.py --help
```

## Parâmetros

| Parâmetro | Obrigatório | Descrição | Padrão |
|---|---|---|---|
| `--csv ARQUIVO` | ✅ | CSV com colunas `cod_imovel`, `x`, `y` (separadas por `;`) | — |
| `--caminho PASTA` | ✅ | Pasta de destino onde serão criadas as subpastas | — |
| `--buffer METROS` | — | Metade do lado do recorte geográfico em metros | `1024` |
| `--largura PIXELS` | — | Largura da imagem de saída em pixels | `1024` |
| `--altura PIXELS` | — | Altura da imagem de saída em pixels | `1024` |
| `--qtd N` | — | Limita às primeiras N linhas do CSV | todas |
| `--workers N` | — | Downloads simultâneos em paralelo | `4` |

---

## Estrutura de Saída

```
<--caminho>/
├── SATELITE/
│   ├── amostra_1.tif
│   ├── amostra_2.tif
│   └── ...
└── SEGMENTADO/
    ├── amostra_1.tif
    ├── amostra_2.tif
    └── ...

artifacts/
└── dataset_manifesto.csv   ← registro de status de cada download

logs/
└── execucao.log            ← log completo da execução
```

---

## Como o Pipeline Funciona — Passo a Passo

O pipeline é composto por **6 etapas sequenciais**, executadas pelo `extrator.py`. As etapas internas de cada download são realizadas de forma paralela e assíncrona.

---

### Etapa 1 — Leitura do CSV de coordenadas

> **Arquivo:** `extrator.py` → função `executar_pipeline_async`
> **Biblioteca:** `pandas`

O pipeline começa lendo o arquivo CSV informado via `--csv`. Esse arquivo contém uma linha por propriedade rural, com o código do imóvel e suas coordenadas geográficas em UTM.

```python
dataframe = pd.read_csv(cfg["arquivo_csv"], sep=";")
```

A biblioteca **pandas** (`pd.read_csv`) lê o arquivo e transforma cada linha em uma linha de um `DataFrame` — uma estrutura de tabela em memória que permite filtrar, iterar e manipular os dados com eficiência. Se o usuário passou `--qtd 1000`, o `DataFrame` é imediatamente truncado para as 1000 primeiras linhas com `.head(1000)`, antes de qualquer download começar.

---

### Etapa 2 — Conversão de coordenadas UTM → Latitude/Longitude

> **Arquivo:** `utils/wms.py` → função `calcular_bbox_latlon`
> **Biblioteca:** `pyproj`

As coordenadas no CSV estão no sistema **EPSG:31984** (UTM zona 24S, em metros). O servidor WMS do GeoBases, porém, exige as coordenadas em **EPSG:4326** (latitude e longitude em graus decimais).

```python
transformador = Transformer.from_crs("EPSG:31984", "EPSG:4326", always_xy=True)
lon_min, lat_min = transformador.transform(xmin_utm, ymin_utm)
lon_max, lat_max = transformador.transform(xmax_utm, ymax_utm)
```

A biblioteca **pyproj** realiza essa projeção cartográfica com precisão geodésica. A partir do ponto central `(x, y)` e do buffer em metros, o código cria uma caixa quadrada ao redor do ponto em UTM, e depois converte os quatro cantos dessa caixa para lat/lon — obtendo o **bounding box** (bbox) que delimita a região geográfica a recortar.

O `Transformer` é criado uma única vez e reutilizado em cache para todas as coordenadas, evitando overhead.

---

### Etapa 3 — Conexão e validação do serviço WMS

> **Arquivo:** `utils/wms.py` → funções `conectar_wms` e `validar_camada`
> **Biblioteca:** `OWSLib`

Antes de qualquer download, o pipeline se conecta ao servidor WMS do GeoBases para verificar se ele está respondendo e se as camadas necessárias existem.

```python
wms = WebMapService("https://ide.geobases.es.gov.br/geoserver/ows", version="1.3.0")
```

A biblioteca **OWSLib** implementa o protocolo **OGC WMS** (Web Map Service) — um padrão internacional para servidores de mapas. Com ela, a simples chamada `WebMapService(url)` já faz o handshake com o servidor, baixa o `GetCapabilities` (catálogo de camadas disponíveis) e expõe o resultado em Python.

Depois da conexão, o pipeline verifica se as duas camadas que serão usadas (`camada_satelite` e `camada_uso_solo`) de fato existem no servidor. Se não existirem, um aviso é registrado no log mas a execução continua — pois a validação é feita só via OWSLib, enquanto os downloads usam `aiohttp` diretamente.

A conexão fica em cache global (`_conexao_wms`) para não se repetir a cada imagem.

---

### Etapa 4 — Download assíncrono das imagens

> **Arquivo:** `utils/wms.py` → funções `requisitar_imagem_wms_async` e `baixar_imagem_async`
> **Bibliotecas:** `aiohttp`, `asyncio`

Esta é a etapa mais crítica e complexa do pipeline. Para cada coordenada, o pipeline precisa baixar **duas imagens** (satélite + segmentado), e isso deve acontecer para **centenas ou milhares de coordenadas** — de forma rápida.

A solução usa **programação assíncrona** com `asyncio` e `aiohttp`:

```python
# Baixar as duas imagens de uma mesma coordenada ao mesmo tempo
status_satelite, status_segmentado = await asyncio.gather(
    _baixar_uma_imagem_async(sessao, cfg, cfg["camada_satelite"], bbox, caminho_satelite),
    _baixar_uma_imagem_async(sessao, cfg, cfg["camada_uso_solo"], bbox, caminho_segmentado),
)
```

**Como funciona na prática:**

- **`asyncio`** é o motor de concorrência do Python. Em vez de bloquear o programa enquanto espera a resposta HTTP, ele "pausa" a operação atual e executa outras enquanto aguarda — como um garçom que anota o pedido de uma mesa e já atende a próxima sem esperar a cozinha.

- **`aiohttp`** é o cliente HTTP assíncrono. Ele envia a requisição `GetMap` ao servidor WMS e aguarda a resposta sem travar o processo. Usa um pool de conexões TCP (`TCPConnector`) para reutilizar conexões abertas ao servidor, reduzindo o custo de handshake.

- **`asyncio.Semaphore`** limita quantas coordenadas são processadas ao mesmo tempo (controlado por `--workers`). Isso evita sobrecarregar o servidor do GeoBases com dezenas de requisições simultâneas.

- **`asyncio.gather`** dispara o download do satélite e do segmentado **em paralelo** para a mesma coordenada — as duas requisições viajam ao servidor ao mesmo tempo.

Em caso de falha (timeout, erro HTTP), o código tenta novamente até 3 vezes com pausa de 2 segundos entre tentativas, antes de registrar o erro no manifesto.

A requisição WMS enviada é um `GetMap` com os parâmetros:

```
SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap
&LAYERS=<nome_da_camada>
&BBOX=<lat_min,lon_min,lat_max,lon_max>
&WIDTH=<largura>&HEIGHT=<altura>
&CRS=EPSG:4326&FORMAT=image/png
```

> **Atenção WMS 1.3.0:** nesta versão do protocolo, o EPSG:4326 exige que o bbox seja passado na ordem `lat,lon` (invertida em relação ao convencional). O código já trata isso em `montar_parametros_wms`.

---

### Etapa 5 — Conversão de PNG para GeoTIFF

> **Arquivo:** `utils/wms.py` → função `salvar_como_geotiff`
> **Bibliotecas:** `Pillow`, `rasterio`, `numpy`

O servidor WMS retorna as imagens em formato **PNG**. Para que sejam úteis em análises geoespaciais (como segmentação por redes neurais), elas precisam ser convertidas para **GeoTIFF georreferenciado** — um formato que embute as coordenadas geográficas dentro do arquivo.

```python
# 1. Decodificar o PNG binário em array numérico
imagem_pil = Image.open(io.BytesIO(conteudo_binario)).convert("RGB")
array_imagem = np.array(imagem_pil)   # shape: (altura, largura, 3)

# 2. Calcular a transformação afim que mapeia pixels → coordenadas
transform_afim = from_bounds(lon_min, lat_min, lon_max, lat_max, largura, altura)

# 3. Escrever o GeoTIFF com metadados geoespaciais
with rasterio.open(caminho, "w", driver="GTiff", crs=CRS.from_epsg(4326),
                   transform=transform_afim, ...) as dst:
    dst.write(array_imagem.transpose(2, 0, 1))
```

Cada biblioteca tem um papel específico:

- **Pillow** (`PIL.Image`) decodifica os bytes binários recebidos do servidor (que estão em formato PNG comprimido) e os converte em uma imagem RGB em memória.

- **numpy** converte a imagem Pillow em um array tridimensional de números inteiros `(altura × largura × 3 canais)`. Esta representação numérica é o que `rasterio` consegue escrever em disco.

- **rasterio** é a biblioteca de referência para I/O de dados raster geoespaciais em Python. Ela escreve o array como um GeoTIFF com:
  - **CRS** (Sistema de Referência de Coordenadas): `EPSG:4326`
  - **Transform afim**: matriz que associa cada pixel a uma posição geográfica real
  - **Compressão LZW**: reduz o tamanho do arquivo sem perda de qualidade

Como a conversão PNG → GeoTIFF é uma operação **CPU-bound** (usa processador, não espera I/O), ela é executada em uma thread separada via `loop.run_in_executor(None, ...)` — para não bloquear o event loop assíncrono enquanto outras imagens estão sendo baixadas.

---

### Etapa 6 — Registro no Manifesto

> **Arquivo:** `utils/manifesto.py` → funções `inicializar_manifesto` e `registrar_resultado`
> **Biblioteca:** `csv` (biblioteca padrão do Python)

Após cada par de imagens ser processado, o resultado é imediatamente registrado no manifesto CSV.

```python
registrar_resultado(
    numero_amostra=1,
    cod_imovel="ES-...",
    x=..., y=...,
    bbox=(lon_min, lat_min, lon_max, lat_max),
    status_satelite="ok",
    status_uso_solo="ok",
)
```

O manifesto é um arquivo CSV em `artifacts/dataset_manifesto.csv` que contém uma linha por coordenada processada, com colunas:

| Coluna | Descrição |
|---|---|
| `numero_amostra` | Número sequencial (1, 2, 3, ...) |
| `cod_imovel` | Código do imóvel no CAR |
| `x`, `y` | Coordenadas UTM originais |
| `bbox_xmin/ymin/xmax/ymax` | Bounding box em graus decimais |
| `status_satelite` | `ok` ou `erro` |
| `status_uso_solo` | `ok` ou `erro` |
| `data_download` | Timestamp ISO 8601 do momento do download |

A biblioteca padrão **`csv`** do Python é usada com `DictWriter`, que escreve dicionários diretamente como linhas CSV — uma por vez, em modo append (`"a"`). Isso garante que o manifesto seja atualizado em tempo real: mesmo que o pipeline seja interrompido no meio, as amostras já processadas ficam registradas.

---

### Barra de Progresso

> **Biblioteca:** `tqdm`

Durante o processamento, o terminal exibe uma barra de progresso em tempo real:

```
Baixando imagens:  42%|████████████          | 420/1000 [03:21<04:38,  2.09img/s]
```

A biblioteca **tqdm** envolve o loop de processamento e atualiza automaticamente a barra a cada imagem concluída, exibindo: percentual, contagem, tempo decorrido, tempo estimado e velocidade (imagens/segundo).

---

### Logging

> **Biblioteca:** `logging` (biblioteca padrão do Python)

Paralelamente à barra de progresso, todos os eventos do pipeline são registrados com timestamp no arquivo `logs/execucao.log` e exibidos no terminal:

```
2025-03-05 14:32:01 [INFO] Conectando ao serviço WMS: https://...
2025-03-05 14:32:03 [INFO] Camada validada: geonode:ijsn-ortofoto...
2025-03-05 14:32:03 [INFO] CSV carregado: 3000 coordenadas encontradas
2025-03-05 14:32:45 [INFO] [amostra_42] SATELITE OK
2025-03-05 14:32:45 [WARNING] Timeout na tentativa 1/3
```

A biblioteca padrão **`logging`** do Python usa dois `handlers` simultâneos: um `FileHandler` (grava no arquivo de log) e um `StreamHandler` (exibe no terminal). O nível `INFO` registra o fluxo normal; erros e avisos aparecem em `WARNING` e `ERROR`.

---

## Diagrama do Fluxo

```
coordenadas.csv
      │
      ▼
 [pandas] lê o CSV
      │
      ▼ para cada coordenada (em paralelo via asyncio.Semaphore)
      │
      ├──► [pyproj] converte UTM → lat/lon → calcula bbox
      │
      ├──► [aiohttp + asyncio] envia GetMap ao GeoBases WMS
      │         │                     │
      │    SATELITE              SEGMENTADO
      │    (em paralelo via asyncio.gather)
      │
      ├──► [Pillow] decodifica PNG → imagem RGB
      ├──► [numpy] converte imagem → array numérico
      ├──► [rasterio] grava GeoTIFF georreferenciado
      │
      └──► [csv] registra resultado no manifesto
                    │
                    ▼
         [tqdm] atualiza barra de progresso
         [logging] grava eventos no log
```

---

## Formato do CSV de Entrada

Separador: **ponto-e-vírgula** (`;`)

| Coluna | Tipo | Descrição |
|---|---|---|
| `cod_imovel` | string | Código do imóvel no CAR |
| `x` | float | Coordenada X em metros (EPSG:31984 — UTM 24S) |
| `y` | float | Coordenada Y em metros (EPSG:31984) |

---

## Estrutura do Projeto

```
projeto-automacao/
├── extrator.py          ← ponto de entrada — CLI e orquestração do pipeline
├── configuracoes.py     ← configurações internas (URLs WMS, camadas, defaults)
├── requirements.txt     ← dependências Python
│
├── utils/
│   ├── wms.py           ← download WMS, conversão bbox, geração de GeoTIFF
│   └── manifesto.py     ← leitura e escrita do CSV de manifesto
│
├── artifacts/           ← gerado automaticamente (manifesto)
├── logs/                ← gerado automaticamente (log de execução)
└── arthur/              ← documentação técnica linha-a-linha de cada arquivo
```
