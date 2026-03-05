# 📦 Tecnologias e Bibliotecas

Referência das bibliotecas utilizadas no pipeline IntegraCar, com descrição do papel de cada uma no projeto.

---

## pandas

**Versão mínima:** `>= 2.2.3`
**Instalação:** incluída no `requirements.txt`

Biblioteca de análise e manipulação de dados tabulares em Python. No projeto, é usada exclusivamente para **ler o CSV de entrada** com as coordenadas UTM das propriedades rurais.

- Lê o arquivo com `pd.read_csv(arquivo, sep=";")` e retorna um `DataFrame`
- Permite truncar facilmente para as primeiras N linhas (`--qtd`) com `.head(N)`
- Itera linha a linha com `.iterrows()` para alimentar o pipeline de downloads

**Não é usada para processamento de imagens ou geoespacial** — apenas para carregar e preparar os dados de entrada.

---

## aiohttp

**Versão mínima:** `>= 3.9.0`

Cliente HTTP **assíncrono** para Python, baseado em `asyncio`. É a biblioteca responsável por toda a comunicação de rede com o servidor WMS do GeoBases.

- Envia requisições `GET` ao endpoint WMS com os parâmetros do `GetMap`
- Usa `TCPConnector` com pool de conexões para reutilizar sockets TCP (keep-alive), reduzindo o custo de conexão para cada imagem
- Configura timeout por requisição (`ClientTimeout`) para evitar que o pipeline fique travado esperando um servidor que não responde
- Em caso de falha (timeout ou erro HTTP), o pipeline retenta até 3 vezes com pausa entre tentativas

Trabalha em conjunto com `asyncio` para permitir que múltiplos downloads ocorram simultaneamente sem bloquear o processo.

---

## asyncio

**Origem:** biblioteca padrão do Python (não requer instalação)

Motor de concorrência assíncrona do Python. Permite executar múltiplas operações de I/O (como downloads HTTP) de forma "concorrente" sem usar múltiplas threads ou processos.

No projeto:

- **`asyncio.Semaphore`** — limita quantas coordenadas são processadas ao mesmo tempo (controlado por `--workers`). Impede que o pipeline envie centenas de requisições simultâneas ao servidor.
- **`asyncio.gather`** — dispara o download do satélite e do segmentado de uma mesma coordenada **em paralelo**, aguardando os dois terminarem antes de continuar.
- **`asyncio.as_completed`** — processa os resultados à medida que ficam prontos, sem esperar que todos terminem para exibir progresso.
- **`loop.run_in_executor`** — executa a conversão PNG → GeoTIFF (operação CPU-bound) em uma thread separada, sem bloquear o event loop.

---

## OWSLib

**Versão mínima:** `>= 0.29.3`

Biblioteca Python para consumir serviços geoespaciais OGC, incluindo **WMS** (Web Map Service), **WFS** e **WCS**. No projeto, é usada apenas na **fase de inicialização e validação**.

- Conecta ao servidor WMS via `WebMapService(url, version="1.3.0")`
- Faz o download automático do `GetCapabilities` — o catálogo de camadas disponíveis no servidor
- Permite verificar se as camadas usadas (`camada_satelite`, `camada_uso_solo`) existem no servidor, exibindo aviso caso contrário

**Não é usada para os downloads em si.** Os downloads das imagens são feitos diretamente com `aiohttp` para permitir comunicação assíncrona, o que OWSLib não suporta.

---

## pyproj

**Versão mínima:** `>= 3.6.1`

Biblioteca de transformações cartográficas e geodésicas, baseada na biblioteca C `PROJ`. É usada para **converter coordenadas** entre sistemas de referência.

No projeto, converte as coordenadas do CSV de **EPSG:31984** (UTM zona 24S, em metros) para **EPSG:4326** (latitude/longitude em graus decimais), que é o sistema exigido pelo servidor WMS.

- Cria um `Transformer` com `from_crs("EPSG:31984", "EPSG:4326", always_xy=True)`
- Aplica a transformação nos quatro cantos do bounding box ao redor de cada ponto central
- O transformador é criado uma única vez e reutilizado em cache para todas as coordenadas

---

## Pillow

**Versão mínima:** `>= 11.1.0`

Biblioteca de processamento de imagens em Python. No pipeline, é usada para **decodificar os bytes PNG** retornados pelo servidor WMS em uma imagem RGB que pode ser manipulada numericamente.

```python
imagem_pil = Image.open(io.BytesIO(conteudo_binario)).convert("RGB")
```

O conteúdo binário recebido via HTTP é carregado diretamente da memória (sem tocar o disco) usando `io.BytesIO`. Pillow o decodifica e normaliza para 3 canais RGB, independente de como o servidor enviou (RGBA, paleta de cores, etc.).

---

## numpy

**Versão mínima:** `>= 2.2.3`

Biblioteca de computação numérica com arrays multidimensionais. No projeto, serve de **ponte entre Pillow e rasterio**.

```python
array_imagem = np.array(imagem_pil)   # shape: (altura, largura, 3)
```

O `rasterio` espera os dados no formato `(bandas, altura, largura)` — o oposto do que Pillow entrega. O numpy faz a transposição do array com `.transpose(2, 0, 1)` antes de gravar o GeoTIFF.

---

## rasterio

**Versão mínima:** `>= 1.4.3`

Biblioteca geoespacial de referência para leitura e escrita de dados **raster** (imagens georreferenciadas). No projeto, é responsável por **criar os arquivos GeoTIFF com georreferenciamento**.

- Recebe o array numpy com os pixels da imagem
- Recebe a **transformação afim** (`from_bounds`) — uma matriz que mapeia cada pixel da imagem a uma posição geográfica real no mundo
- Recebe o **CRS** (`CRS.from_epsg(4326)`) — o sistema de coordenadas embutido no arquivo
- Grava o arquivo `.tif` com compressão **LZW** (sem perda de qualidade, reduz o tamanho em disco)

O resultado é um arquivo que qualquer software GIS (QGIS, ArcGIS, GDAL) consegue abrir já posicionado corretamente no mapa.

---

## tqdm

**Versão mínima:** `>= 4.67.1`

Biblioteca de barra de progresso para loops Python. Exibe em tempo real o andamento do pipeline no terminal:

```
Baixando imagens:  42%|████████        | 420/1000 [03:21<04:38, 2.09img/s]
```

Mostra: percentual completo, contagem absoluta, tempo decorrido, tempo estimado e velocidade de processamento. Requer apenas envolver o loop com `tqdm(total=N, ...)` e chamar `barra.update(1)` a cada item concluído.

---

## csv + logging + pathlib + datetime

**Origem:** biblioteca padrão do Python (não requerem instalação)

Módulos nativos usados para infra-estrutura do pipeline:

| Módulo | Uso no projeto |
|---|---|
| `csv` (`DictWriter`/`DictReader`) | Lê e escreve o manifesto `dataset_manifesto.csv` linha a linha, em modo append |
| `logging` | Grava eventos com timestamp em `logs/execucao.log` e exibe no terminal simultaneamente |
| `pathlib.Path` | Manipula caminhos de arquivos e pastas de forma independente de SO; cria diretórios com `mkdir(parents=True, exist_ok=True)` |
| `datetime` | Gera o timestamp ISO 8601 registrado no manifesto a cada download concluído |

---

## Resumo

| Biblioteca | Papel principal |
|---|---|
| `pandas` | Leitura e filtragem do CSV de coordenadas |
| `aiohttp` | Requisições HTTP assíncronas ao servidor WMS |
| `asyncio` | Motor de concorrência: paralelismo de downloads e controle de semáforo |
| `OWSLib` | Conexão inicial e validação das camadas WMS |
| `pyproj` | Conversão de coordenadas UTM → lat/lon |
| `Pillow` | Decodificação de PNG binário em imagem RGB |
| `numpy` | Ponte numérica entre Pillow e rasterio |
| `rasterio` | Geração de GeoTIFFs georreferenciados com CRS e transformação afim |
| `tqdm` | Barra de progresso no terminal |
| `csv` | Leitura e escrita do manifesto CSV |
| `logging` | Log com timestamp em arquivo e terminal |
| `pathlib` | Manipulação de caminhos e criação de pastas |
