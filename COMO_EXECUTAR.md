# Como Executar o IntegraCar — Guia Passo a Passo

---

## Pré-requisitos

### 1. Instalar Python 3.10+

Verifique se o Python está instalado:

```bash
python3 --version
```

### 2. Criar e ativar o ambiente virtual

```bash
cd projeto-automacao

# Criar (apenas na primeira vez)
python3 -m venv venv

# Ativar
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

> Isso instala todas as bibliotecas necessárias: pandas, aiohttp, rasterio,
> pystac-client, planetary-computer, etc.

---

## Opção 1: Interface Gráfica (Tkinter)

### Passo 1 — Abrir a GUI

```bash
python main.py gui
```

A janela do IntegraCar será aberta.

### Passo 2 — Selecionar o CSV de coordenadas

- Clique em **"Selecionar..."** ao lado de **"Arquivo CSV"**
- Navegue até o arquivo CSV (ex: `coordenadas_treino_amostra.csv`)
- O CSV deve ter colunas `cod_imovel`, `x`, `y` separadas por `;`

### Passo 3 — Selecionar a pasta de saída

- Clique em **"Selecionar..."** ao lado de **"Pasta de Saída"**
- Escolha ou crie uma pasta onde as imagens serão salvas

### Passo 4 — Escolher o satélite

- No dropdown **"Satélite"**, selecione uma das opções:
  - `kompsat` — imagem RGB 0.5m (GeoBases ES, via WMS)
  - `sentinel` — Sentinel-2 10m (Planetary Computer, via STAC)
  - `landsat` — Landsat 8/9 30m + banda termal (Planetary Computer, via STAC)
  - `cbers` — CBERS-4A 2m (catálogo brasileiro INPE, via STAC)

### Passo 5 — Configurar parâmetros (opcional)

| Campo | O que faz | Valor padrão |
|-------|-----------|--------------|
| Cloud Cover (%) | Máximo de nuvens aceito na cena | 20 |
| Buffer (m) | Metade do lado do recorte em metros | 1024 |
| Largura (px) | Largura da imagem de saída | 1024 |
| Altura (px) | Altura da imagem de saída | 1024 |
| Limite amostras | Processar apenas as N primeiras coordenadas (vazio = todas) | — |

### Passo 6 — Camada segmentada (opcional)

- Marque o checkbox **"Baixar camada segmentada (apenas GeoBases ES)"** se quiser
  baixar também a camada de uso do solo
- Funciona apenas com coordenadas dentro do Espírito Santo

### Passo 7 — Iniciar

- Clique no botão **"INICIAR"**
- Acompanhe:
  - **Barra de progresso** — mostra quantas imagens foram processadas
  - **Log em tempo real** — exibe cada download, erro e status
- Aguarde até a mensagem de conclusão aparecer na barra de status

### Passo 8 — Verificar resultados

As imagens estarão na pasta de saída escolhida:

```
pasta_saida/
├── SATELITE/
│   ├── amostra_1.tif
│   ├── amostra_2.tif
│   └── ...
└── SEGMENTADO/          (se marcou a checkbox)
    ├── amostra_1.tif
    └── ...
```

O manifesto com os metadados fica em `artifacts/dataset_manifesto.csv`.

---

## Opção 2: Linha de Comando (CLI)

### Uso básico

```bash
python main.py run --csv <ARQUIVO_CSV> --satellite <SATELITE>
```

### Exemplos práticos

#### Exemplo 1: KOMPSAT (legado, igual ao pipeline original)

```bash
python main.py run \
  --csv coordenadas_treino_amostra.csv \
  --satellite kompsat \
  --layer true
```

#### Exemplo 2: Sentinel-2 com filtro de nuvens

```bash
python main.py run \
  --csv coordenadas_treino_amostra.csv \
  --satellite sentinel \
  --cloud 15 \
  -o saida_sentinel
```

#### Exemplo 3: Landsat (inclui banda termal TIR)

```bash
python main.py run \
  --csv coordenadas_treino_amostra.csv \
  --satellite landsat \
  --cloud 20 \
  --buffer 2048 \
  -o saida_landsat
```

#### Exemplo 4: CBERS-4A (satélite brasileiro, 2m)

```bash
python main.py run \
  --csv coordenadas_treino_amostra.csv \
  --satellite cbers \
  --cloud 30 \
  -o saida_cbers
```

#### Exemplo 5: Teste rápido (apenas 5 imagens)

```bash
python main.py run \
  --csv coordenadas_treino_amostra.csv \
  --satellite sentinel \
  --limit 5 \
  --cloud 20
```

#### Exemplo 6: Configuração completa

```bash
python main.py run \
  --csv coordenadas_treino_amostra.csv \
  --satellite sentinel \
  --cloud 20 \
  --layer true \
  --buffer 512 \
  --width 512 \
  --height 512 \
  --workers 8 \
  --limit 100 \
  --date-start 2023-06-01 \
  --date-end 2024-01-01 \
  -o dataset_final
```

### Parâmetros CLI disponíveis

| Parâmetro | Obrigatório | Descrição |
|-----------|:-----------:|-----------|
| `--csv` | Sim | Caminho do CSV de coordenadas |
| `--satellite`, `-s` | Não | Satélite: `kompsat`, `sentinel`, `landsat`, `cbers` (padrão: kompsat) |
| `--output`, `-o` | Não | Pasta de saída (padrão: `saida`) |
| `--cloud` | Não | % máximo de nuvens (padrão: 20) |
| `--layer` | Não | Baixar camada segmentada: `true` ou `false` (padrão: false) |
| `--buffer` | Não | Buffer em metros (padrão: 1024) |
| `--width` | Não | Largura em pixels (padrão: 1024) |
| `--height` | Não | Altura em pixels (padrão: 1024) |
| `--workers` | Não | Workers paralelos (padrão: 4) |
| `--limit` | Não | Limitar a N coordenadas |
| `--date-start` | Não | Data inicial YYYY-MM-DD (padrão: 2023-01-01) |
| `--date-end` | Não | Data final YYYY-MM-DD (padrão: 2024-12-31) |
| `--config` | Não | Caminho para config.yaml alternativo |

### Outros comandos

```bash
# Listar satélites disponíveis
python main.py list-satellites

# Abrir a GUI via CLI
python main.py gui

# Ajuda geral
python main.py --help

# Ajuda do comando run
python main.py run --help
```

---

## Formato do CSV de Entrada

O CSV deve ter separador `;` e as colunas:

```
cod_imovel;x;y
ES-1234567-ABC;357900.0;7756200.0
ES-9876543-DEF;358100.0;7756400.0
```

- `cod_imovel` — identificador do imóvel
- `x` — coordenada X em metros (UTM, EPSG:31984)
- `y` — coordenada Y em metros (UTM, EPSG:31984)

---

## Estrutura de Saída

```
pasta_saida/
├── SATELITE/                    # Imagens do satélite escolhido
│   ├── amostra_1.tif           # GeoTIFF georreferenciado
│   ├── amostra_2.tif
│   └── ...
├── SEGMENTADO/                  # Uso do solo (se --layer true)
│   ├── amostra_1.tif
│   └── ...
artifacts/
├── dataset_manifesto.csv        # Registro de cada download
logs/
├── execucao.log                 # Log detalhado da execução
```

---

## Resolução de Problemas

| Problema | Solução |
|----------|---------|
| `ModuleNotFoundError` | Execute `pip install -r requirements.txt` no venv ativado |
| `Nenhuma cena encontrada` (STAC) | Aumente `--cloud` ou ajuste `--date-start`/`--date-end` |
| Imagens pretas/vazias | A coordenada pode estar fora da cobertura do satélite |
| Download muito lento | Reduza `--buffer` e dimensões, ou aumente `--workers` |
| `WMS retornou erro` | Servidor GeoBases pode estar fora do ar; tente mais tarde |
| GUI não abre | Verifique se o Tkinter está instalado: `python -c "import tkinter"` |

---

## Pipeline Legado (extrator.py)

O pipeline original continua disponível para compatibilidade:

```bash
python extrator.py
```

Abre a GUI antiga com suporte a processamento 2012 e 2019-2020 via WMS.
