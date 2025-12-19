# Guida Completa al Coverage (Copertura del Codice)

## 📚 Cos'è il Coverage?

Il **coverage** (copertura del codice) misura **quanto del tuo codice viene eseguito durante i test**. È una metrica che indica quali righe, funzioni, classi e branch del codice sono state testate.

### Perché è Importante?

- ✅ **Trova codice non testato**: Identifica parti del codice mai eseguite
- ✅ **Misura qualità test**: Verifica se i test coprono tutto il codice
- ✅ **Priorità**: Aiuta a decidere cosa testare prima
- ✅ **CI/CD**: Può bloccare deploy se coverage troppo bassa

## 🔢 Come si Calcola?

### Metrica Base: Line Coverage

Il coverage si calcola come:

```
Coverage % = (Righe Eseguite / Righe Totali) × 100
```

**Esempio**:
- Codice totale: 1000 righe
- Righe eseguite dai test: 750 righe
- **Coverage: 75%**

### Tipi di Coverage

#### 1. **Line Coverage** (Copertura Righe)
Misura quante righe di codice sono state eseguite.

```python
def calculate_total(items):
    total = 0           # ✅ Eseguita
    for item in items: # ✅ Eseguita
        total += item  # ✅ Eseguita (se items non è vuoto)
    return total       # ✅ Eseguita

# Test che esegue questa funzione = 100% line coverage
```

#### 2. **Branch Coverage** (Copertura Branch)
Misura se tutti i branch (if/else, try/except) sono stati testati.

```python
def process_item(item):
    if item is None:      # Branch 1: ✅ testato
        return None
    elif item < 0:       # Branch 2: ❌ NON testato
        return -item
    else:                 # Branch 3: ✅ testato
        return item

# Line coverage: 100% (tutte le righe eseguite)
# Branch coverage: 66% (solo 2 branch su 3 testati)
```

#### 3. **Function Coverage** (Copertura Funzioni)
Misura quante funzioni sono state chiamate almeno una volta.

```python
def func_a():  # ✅ Chiamata nei test
    pass

def func_b():  # ❌ Mai chiamata
    pass

def func_c():  # ✅ Chiamata nei test
    pass

# Function coverage: 66% (2 funzioni su 3)
```

#### 4. **Statement Coverage** (Copertura Statement)
Simile a line coverage, ma conta le istruzioni invece delle righe.

## 🛠️ Come Usare Coverage con pytest

### Installazione

```bash
pip install pytest-cov
```

### Comandi Base

#### 1. Coverage Terminale (Testo)

```bash
pytest --cov=sync_calimob --cov-report=term
```

**Output**:
```
Name                          Stmts   Miss  Cover   Missing
------------------------------------------------------------
sync_calimob/sync_mapper.py     150     30    80%   45-50, 120-125
sync_calimob/rest_client.py     200     50    75%   100-120
------------------------------------------------------------
TOTAL                           350     80    77%
```

**Spiegazione**:
- `Stmts`: Statement totali nel file
- `Miss`: Statement non eseguiti
- `Cover`: Percentuale coverage
- `Missing`: Righe non coperte

#### 2. Coverage HTML (Interattivo)

```bash
pytest --cov=sync_calimob --cov-report=html
```

Genera `htmlcov/index.html` - apri nel browser per vedere:
- ✅ Righe verdi = coperte
- ❌ Righe rosse = non coperte
- ⚠️ Righe gialle = parzialmente coperte (branch)

#### 3. Coverage XML (CI/CD)

```bash
pytest --cov=sync_calimob --cov-report=xml
```

Genera `coverage.xml` per integrazione CI/CD (es. GitHub Actions, GitLab CI).

#### 4. Coverage JSON

```bash
pytest --cov=sync_calimob --cov-report=json
```

Genera `coverage.json` per analisi programmatica.

### Opzioni Avanzate

#### Escludere File

```bash
# Escludi file di test
pytest --cov=sync_calimob --cov-report=html \
  --cov-config=.coveragerc

# .coveragerc:
[run]
omit = 
    */tests/*
    */test_*.py
    */__pycache__/*
```

#### Coverage Minimo

```bash
# Fallisce se coverage < 80%
pytest --cov=sync_calimob --cov-report=term \
  --cov-fail-under=80
```

#### Solo Specifici Moduli

```bash
# Coverage solo per sync_mapper
pytest --cov=sync_calimob.sync_mapper --cov-report=term

# Coverage per più moduli
pytest --cov=sync_calimob.sync_mapper \
       --cov=sync_calimob.rest_client \
       --cov-report=term
```

## 📊 Interpretare i Risultati

### Esempio Output Terminale

```
Name                          Stmts   Miss  Cover   Missing
------------------------------------------------------------
sync_calimob/__init__.py        50      5    90%   45-50
sync_calimob/sync_mapper.py    150     30    80%   45-50, 120-125
sync_calimob/rest_client.py    200     50    75%   100-120
sync_calimob/sync_worker.py    300    100    66%   200-250, 280-300
------------------------------------------------------------
TOTAL                          700    185    73%
```

### Cosa Significa?

1. **`sync_mapper.py: 80%`**
   - ✅ Buono: La maggior parte del codice è testata
   - ⚠️ Righe 45-50 e 120-125 non sono coperte
   - **Azione**: Aggiungi test per quelle righe

2. **`sync_worker.py: 66%`**
   - ⚠️ Basso: Un terzo del codice non è testato
   - ❌ Righe 200-250 e 280-300 non sono coperte
   - **Azione**: Priorità alta - aggiungi test

3. **`TOTAL: 73%`**
   - ✅ Buono per progetto medio
   - ⚠️ Sotto target 75%
   - **Azione**: Migliora coverage di `sync_worker.py`

### Esempio HTML Report

Aprendo `htmlcov/index.html` vedrai:

```
sync_calimob/
├── __init__.py (90% coverage)
│   ├── ✅ Righe 1-44: verdi (coperte)
│   ├── ❌ Righe 45-50: rosse (non coperte)
│   └── ✅ Righe 51+: verdi (coperte)
│
├── sync_mapper.py (80% coverage)
│   ├── ✅ calibre_to_json_item(): verde
│   ├── ❌ json_item_to_calibre(): parzialmente giallo
│   └── ✅ calculate_cover_hash(): verde
│
└── rest_client.py (75% coverage)
    ├── ✅ _request(): verde
    ├── ❌ _handle_error(): rosso (non testato)
    └── ⚠️ upload_cover(): giallo (branch non testato)
```

## 🎯 Target Coverage

### Linee Guida Generali

| Tipo di Codice | Coverage Target | Motivo |
|----------------|-----------------|--------|
| **Funzioni critiche** | 90-100% | Bug qui = problemi gravi |
| **Business logic** | 80-90% | Logica core deve essere testata |
| **Utility/Helper** | 70-80% | Codice semplice, meno critico |
| **UI/Views** | 50-70% | Difficile testare, meno critico |
| **Totale progetto** | 75-85% | Bilanciamento pratico |

### Per il Plugin sync_calimob

```
Target Coverage:
├── sync_mapper.py:        80%+  (conversioni critiche)
├── rest_client.py:        75%+  (API client importante)
├── sync_worker.py:        70%+  (logica complessa)
├── library_utils.py:      80%+  (utility pure)
├── config.py:             60%+  (UI, meno critico)
└── TOTALE:                75%+  (bilanciamento)
```

## 📈 Migliorare il Coverage

### Strategia Step-by-Step

#### 1. Identifica Codice Non Coperto

```bash
# Genera report HTML
pytest --cov=sync_calimob --cov-report=html

# Apri htmlcov/index.html
# Cerca righe rosse (non coperte)
```

#### 2. Analizza Perché Non è Coperto

**Possibili motivi**:
- ❌ Nessun test per quella funzione
- ❌ Test non copre tutti i branch (if/else)
- ❌ Codice morto (mai usato)
- ❌ Error handling non testato

#### 3. Aggiungi Test

**Esempio**: Righe 45-50 non coperte in `sync_mapper.py`

```python
# sync_mapper.py (righe 45-50)
def calibre_to_json_item(...):
    if not metadata.title:  # ❌ Non testato
        item['title'] = ''  # ❌ Non testato
    else:
        item['title'] = metadata.title

# Aggiungi test:
def test_calibre_to_json_item_without_title():
    """Test conversione senza titolo."""
    metadata = Metadata('')
    item = calibre_to_json_item(123, metadata, 'lib-id')
    assert item['title'] == ''  # ✅ Ora coperto!
```

#### 4. Verifica Miglioramento

```bash
# Prima: 80% coverage
# Dopo: 85% coverage ✅
pytest --cov=sync_calimob --cov-report=term
```

## 🔍 Esempi Pratici

### Esempio 1: Coverage Base

```python
# sync_mapper.py
def calculate_total(items):
    total = 0
    for item in items:
        total += item
    return total

# test_sync_mapper.py
def test_calculate_total():
    result = calculate_total([1, 2, 3])
    assert result == 6

# Coverage: 100% ✅
```

### Esempio 2: Branch Coverage

```python
# sync_mapper.py
def process_item(item):
    if item is None:
        return None
    elif item < 0:
        return -item
    else:
        return item

# test_sync_mapper.py
def test_process_item_positive():
    assert process_item(5) == 5  # ✅ Branch 3

def test_process_item_none():
    assert process_item(None) is None  # ✅ Branch 1

# ❌ Manca test per item < 0 (Branch 2)
# Coverage: 66% (branch), 100% (line)
```

**Aggiungi test**:
```python
def test_process_item_negative():
    assert process_item(-5) == 5  # ✅ Branch 2
# Coverage: 100% ✅
```

### Esempio 3: Error Handling

```python
# rest_client.py
def get_data(url):
    try:
        response = requests.get(url)
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error: {e}")  # ❌ Non testato
        return None

# test_rest_client.py
def test_get_data_success():
    # ✅ Test caso successo
    result = get_data('https://api.example.com')
    assert result is not None

# ❌ Manca test per errore
# Coverage: 66%
```

**Aggiungi test**:
```python
@responses.activate
def test_get_data_error():
    responses.add(responses.GET, 'https://api.example.com', 
                  body=Exception('Network error'))
    result = get_data('https://api.example.com')
    assert result is None  # ✅ Ora coperto!
# Coverage: 100% ✅
```

## ⚙️ Configurazione Avanzata

### File `.coveragerc`

Crea `tests/plugin/.coveragerc`:

```ini
[run]
source = sync_calimob
omit = 
    */tests/*
    */test_*.py
    */__pycache__/*
    */venv/*
    */site-packages/*

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
    if TYPE_CHECKING:
    @abstractmethod

precision = 2
show_missing = True
skip_covered = False

[html]
directory = htmlcov
title = sync_calimob Coverage Report
```

### Uso con pytest.ini

```ini
# pytest.ini
[pytest]
addopts = 
    --cov=sync_calimob
    --cov-report=term-missing
    --cov-report=html
    --cov-fail-under=75
```

## 🚀 CI/CD Integration

### GitHub Actions

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: |
          pip install -r tests/plugin/requirements.txt
      - name: Run tests with coverage
        run: |
          cd tests/plugin
          pytest --cov=sync_calimob --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
        with:
          file: ./coverage.xml
```

## 📝 Best Practices

### ✅ DO

1. **Target realistici**: 75-85% è buono, 100% spesso non pratico
2. **Priorità**: Focus su codice critico (business logic)
3. **Branch coverage**: Testa tutti i branch (if/else)
4. **Error handling**: Testa anche casi di errore
5. **Review regolare**: Controlla coverage dopo ogni feature

### ❌ DON'T

1. **Non ossessionarsi**: 100% coverage non significa 0 bug
2. **Non testare codice morto**: Se codice non usato, rimuovilo
3. **Non ignorare branch**: Line coverage 100% ma branch 50% = problema
4. **Non falsare**: Non aggiungere test inutili solo per coverage
5. **Non dimenticare edge cases**: Testa anche casi limite

## 🎓 Esercizi Pratici

### Esercizio 1: Calcola Coverage Manuale

```python
# file.py (10 righe totali)
def func_a():      # Righe 1-3
    return 1

def func_b():      # Righe 5-7
    return 2

def func_c():      # Righe 9-10
    return 3

# test_file.py
def test_func_a():
    assert func_a() == 1  # Esegue righe 1-3

def test_func_b():
    assert func_b() == 2  # Esegue righe 5-7

# Domanda: Qual è il coverage?
# Risposta: 6 righe eseguite / 10 righe totali = 60%
```

### Esercizio 2: Migliora Coverage

```python
# sync_mapper.py
def process_rating(rating):
    if rating < 0:        # Branch 1
        return 0
    elif rating > 5:      # Branch 2
        return 5
    else:                 # Branch 3
        return rating

# test_sync_mapper.py
def test_process_rating_normal():
    assert process_rating(3) == 3  # ✅ Branch 3

# Coverage attuale: 33% (branch)
# Cosa aggiungere per 100%?
```

**Soluzione**:
```python
def test_process_rating_negative():
    assert process_rating(-1) == 0  # ✅ Branch 1

def test_process_rating_too_high():
    assert process_rating(10) == 5  # ✅ Branch 2
# Coverage: 100% ✅
```

## 📚 Risorse

- [pytest-cov Documentation](https://pytest-cov.readthedocs.io/)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)
- [Understanding Code Coverage](https://martinfowler.com/bliki/TestCoverage.html)

## 🎯 Riepilogo

1. **Coverage** = % di codice eseguito durante i test
2. **Calcolo**: `(Righe Eseguite / Righe Totali) × 100`
3. **Tipi**: Line, Branch, Function, Statement
4. **Target**: 75-85% per progetto medio
5. **Tool**: `pytest --cov` per misurare
6. **Miglioramento**: Aggiungi test per codice non coperto
