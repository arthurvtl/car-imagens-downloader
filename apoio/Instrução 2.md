# Instrução 2 — Análise do Repositório BigEarthNet Pipeline e Aproveitamento para o IntegraCar

**Repositório analisado:** https://github.com/rsim-tu-berlin/bigearthnet-pipeline  
**Origem:** TU Berlin / RSiM Group — pipeline para criar o dataset BigEarthNet v2 a partir de imagens Sentinel-2

---

## 1. O que é o BigEarthNet Pipeline?

É um pipeline de criação de dataset de sensoriamento remoto para visão computacional. Em alto nível, ele:

1. Baixa tiles de satélite Sentinel-2 do Copernicus (ESA)
2. Converte imagens L1C → L2A (pré-processamento atmosférico com sen2cor)
3. **Divide os tiles em patches de 1200m × 1200m ao redor de coordenadas-alvo**
4. **Associa cada patch de imagem bruta a um mapa de referência de classes (segmentação pixel a pixel)**
5. Gera arquivos CSV de metadados (mapeamento patch → label, patch → split train/val/test)
6. Verifica integridade dos dados com hashes SHA256
7. Comprime tudo para distribuição

**Stack tecnológica:** Nix, Nushell, PostgreSQL/PostGIS, Flyway, pueue

---

## 2. Paralelo Direto com o IntegraCar

O BigEarthNet resolve **exatamente o mesmo problema conceitual** que o nosso:

| BigEarthNet | IntegraCar |
|---|---|
| Tile Sentinel-2 (imagem bruta) | Ortomosaico KOMPSAT 2019/2020 (imagem bruta) |
| Mapa de referência CORINE Land Cover | Mapa Uso do Solo IJSN (segmentação colorida) |
| Par (imagem_bruta, mapa_labels) por patch | Par (satelite.tif, uso_solo.tif) por imóvel |
| Coordenadas dos patches em CSV | `coordenadas_treino_amostra.csv` |
| metadata/patch_id_label_mapping.csv | manifesto do dataset a criar |
| Split train/val/test em CSV separado | Divisão futura do nosso dataset |

A ideia central é **idêntica**: dado um conjunto de coordenadas, recortar dois rasters diferentes (bruto + segmentado) e organizar os pares com metadados rastreáveis.

---

## 3. O que podemos aproveitar diretamente (conceitos e práticas)

### 3.1 Estrutura de Patch por Coordenada (✅ Aproveitar)

O BigEarthNet define um **bounding box fixo** ao redor de cada coordenada central para criar o recorte (patch). Faremos o mesmo com nosso `buffer_metros`.

```
ponto (x, y) → bbox = (x - buffer, y - buffer, x + buffer, y + buffer)
```

Isso garante que todos os patches tenham o mesmo tamanho e sejam comparáveis entre si — fundamental para treinar um modelo de segmentação semântica.

### 3.2 Par de Imagens por Amostra (✅ Aproveitar)

O BigEarthNet organiza o dataset como pares `(imagem_bruta, mapa_referência)` em diretórios nomeados pelo ID do patch. Adotaremos exatamente essa estrutura:

```
saida/
├── {cod_imovel}/
│   ├── satelite.tif        ← GeoTIFF 1024×1024, EPSG:31984
│   └── uso_solo.tif        ← GeoTIFF 1024×1024, EPSG:31984
```

### 3.3 Arquivo de Manifesto / Metadados (✅ Aproveitar — muito importante)

O BigEarthNet mantém arquivos CSV separados:
- `patch_id_label_mapping.csv`: qual label pertence a qual patch
- `patch_id_split_mapping.csv`: qual patch é treino/validação/teste

**Para o IntegraCar, criaremos um `dataset_manifesto.csv`** gerado automaticamente durante o download:

```csv
cod_imovel;x;y;bbox_xmin;bbox_ymin;bbox_xmax;bbox_ymax;status;hash_satelite;hash_uso_solo;data_download
ES-3200136-AED7...;317411.4;7898046.9;316911.4;7897546.9;317911.4;7898546.9;ok;a3f2...;b91c...;2026-03-02
```

Isso permite: rastrear o que foi baixado, detectar arquivos corrompidos e dividir o dataset em treino/validação/teste futuramente.

### 3.4 Verificação de Integridade com SHA256 (✅ Aproveitar)

O BigEarthNet gera hashes SHA256 de cada arquivo TIFF e armazena como referência. Se rodar o pipeline novamente, compara os hashes para detectar mudanças nos dados brutos.

**Para nós:** ao baixar cada imagem, gerar e registrar o hash no manifesto. Se a imagem já existe no disco e o hash bate, pular o download (comportamento **idempotente**).

```python
import hashlib

def calcular_hash_arquivo(caminho_arquivo: str) -> str:
    hash_sha256 = hashlib.sha256()
    with open(caminho_arquivo, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(8192), b""):
            hash_sha256.update(bloco)
    return hash_sha256.hexdigest()
```

### 3.5 Download Idempotente (✅ Aproveitar)

O BigEarthNet pula tiles que já foram baixados com sucesso. O README menciona:
> *"it will skip over already successfully downloaded tiles"*

**Para nós:** antes de fazer uma requisição WMS, verificar se o arquivo já existe no disco. Isso permite:
- Retomar downloads interrompidos
- Reprocessar apenas os pontos que falharam
- Não sobrecarregar o servidor GeoBases desnecessariamente

### 3.6 Separação de Configuração do Código (✅ Aproveitar)

O BigEarthNet usa variáveis de ambiente (`.envrc`) para separar configurações do código. Faremos o mesmo com um arquivo `configuracoes.py` ou `.env`, evitando hardcode de caminhos e nomes de camadas.

### 3.7 Arquivos de Referência Versionados (`tracked-artifacts`) (✅ Aproveitar)

O repositório mantém uma pasta `tracked-artifacts/` com CSVs de referência e checksums versionados no Git. Eles detectaram que o próprio servidor Copernicus mudou arquivos sem aviso — o hash revelou isso.

**Para nós:** versionar o `dataset_manifesto.csv` no Git como referência do estado atual do dataset.

---

## 4. O que NÃO aproveitar (e por quê)

| Componente BigEarthNet | Por que não usar no IntegraCar |
|---|---|
| **Nix / NixOS** | Sistema de build extremamente complexo, voltado para reprodutibilidade em nível de datacenter. Python `venv` + `requirements.txt` resolve nosso problema com muito menos custo |
| **Nushell** | Shell exótico, não padrão. Usaremos Python que a equipe já conhece |
| **PostgreSQL + PostGIS** | Overkill para ~200 imagens de amostra. Arquivos CSV + pastas são suficientes |
| **Flyway (migrações de schema)** | Voltado para evolução de banco de dados em produção. Irrelevante sem banco |
| **pueue (task queue)** | Sistema de fila de jobs para servidores. Para nossa escala, `concurrent.futures` no Python é suficiente |
| **sen2cor (L1C → L2A)** | Pré-processamento específico do Sentinel-2. Nosso pipeline consome dados já processados via WMS |
| **ZSTD compression pipeline** | Nossa base de dados é pequena o suficiente para não precisar de compressão de distribuição por ora |

---

## 5. Estrutura de Projeto Inspirada no BigEarthNet

Adaptando as boas práticas do repositório para o nosso contexto Python/WMS:

```
projeto-automacao/
├── configuracoes.py            ← parâmetros centralizados (camadas, buffer, paths)
├── extrator.py                 ← script principal de download
├── utils/
│   ├── wms.py                  ← funções de requisição WMS
│   ├── manifesto.py            ← leitura/escrita do CSV de metadados
│   └── integridade.py          ← geração e verificação de hashes SHA256
├── saida/                      ← pares de GeoTIFF 1024×1024 (não versionar no Git)
│   └── {cod_imovel}/
│       ├── satelite.tif
│       └── uso_solo.tif
├── artifacts/                  ← arquivos de referência versionados no Git
│   └── dataset_manifesto.csv   ← registro de todos os downloads
├── coordenadas_treino_amostra.csv
├── requirements.txt
└── venv/
```

---

## 6. Resumo: Aproveitamento Real do BigEarthNet

| Conceito | Aproveitamos? | Como |
|---|---|---|
| Estrutura de diretório por patch/ID | ✅ Sim | `saida/{cod_imovel}/satelite.tif` |
| Par imagem bruta + mapa de referência | ✅ Sim | Download das 2 camadas WMS por ponto |
| CSV de manifesto/metadados | ✅ Sim | `dataset_manifesto.csv` com hash e status |
| Hash SHA256 para integridade | ✅ Sim | Verificar/pular downloads existentes |
| Downloads idempotentes | ✅ Sim | Checar arquivo antes de baixar |
| Tracked artifacts versionados | ✅ Sim | Manifesto no Git |
| Separação config/código | ✅ Sim | `configuracoes.py` |
| Nix, Nushell, PostgreSQL, Flyway | ❌ Não | Complexidade desnecessária para o escopo |

> **Conclusão:** O BigEarthNet pipeline não pode ser usado diretamente — a stack tecnológica (Nix, Nushell, PostgreSQL) é inviável para o nosso contexto. Mas ele é uma referência de **arquitetura e boas práticas** extremamente relevante: a estrutura de pares de imagens, o CSV de manifesto com hashes, os downloads idempotentes e os arquivos de referência versionados são padrões que adotaremos diretamente na nossa implementação Python.
