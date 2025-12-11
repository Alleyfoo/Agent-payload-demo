# Agent-learning

Moniagenttisen "piiriarkkitehtuurin" v1-MVP, jossa keskitetty PuhemiesAgentti orkestroi kolme sisäistä piiriä ja VarjoAgentti tallentaa juoksukohtaisen analyysin. Toteutus käyttää FastAPI:a ja on paketoitavissa Dockerilla.

## Arkkitehtuurin pääosat

- **PuhemiesAgentti (`SpeakerAgent`)**: ainoa rajapinta käyttäjään. Luodaan `run_id`, reititetään viesti piireihin ja yhdistetään tulokset.
- **Piiri A (Intentio + Konteksti)**: koostaa `TaskSpec`-rakenteen käyttäjän viestistä.
- **Piiri B (Metodi + Tuottaja)**: määrittää oletusmetodin (`lesson_v1`) ja tuottaa sisällön LLM:n avulla.
- **Piiri C (Tarkastaja + Tuomari)**: tarkastaa, että sisältö noudattaa metodia ja antaa päätöksen (accept/revise).
- **VarjoAgentti**: kuuntelee kaikki viestit, laskee drift-scoren sekä lisämittoja (faktatarkkuus, kielioppi/sujuvuus) ja tallentaa JSONL-raportin `data/shadow_reports.jsonl`.

## Käyttö

### Kehitysympäristö

1. Asenna riippuvuudet:
   ```bash
   pip install -r requirements.txt
   ```
2. Käynnistä sovellus:
   ```bash
   uvicorn app.main:app --reload
   ```
3. Lähetä pyyntö:
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Tarvitsen oppitunnin Python-lista comprehensioneista suomeksi"}'
   ```

### Docker

```bash
docker-compose up --build
```

Säilöö `data/`-hakemiston kontista isäntään.

## LLM-integraatio

`LLMClient` hyödyntää Ollaman HTTP-rajapintaa (oletusosoite `http://localhost:11434`). Jos muuttuja `OLLAMA_USE_MOCK=1`, käytetään sisäistä mockia, joka tuottaa deterministisiä esimerkkivastauksia ilman Ollamaa.

## Projektirakenne

- `app/main.py`: FastAPI-rajapinta (/chat)
- `app/speaker.py`: PuhemiesAgentin orkestrointi
- `app/circuits/*`: piirit (Intentio/Konteksti, Metodi/Tuottaja, Tarkastus/Tuomari)
- `app/agents/shadow.py`: VarjoAgentin lokitus, drift-metriikat ja juoksukohtaiset aggregaatit
- `app/utils/llm_client.py`: Ollama-kutsu tai mock
- `data/`: VarjoAgentin raportit (JSONL)

## VarjoAgentin raportointi ja metriikat

VarjoAgentti kerää jokaisesta ajosta sekä juoksukohtaiset mitat että kumulatiiviset aggregaatit ja kirjoittaa ne JSONL-riviin tiedostoon `data/shadow_reports.jsonl`.

### Uudet mittarit

- **`fact_accuracy_score`**: heuristinen arvio faktatarkkuudesta (`1.0` kun `potential_hallucinations` on tyhjä, −0.15 per havaittu riski, minimi `0.4`).
- **`grammar_clarity_score`**: kieliopin ja luettavuuden pistemäärä (perustuu tekstin keskimääräiseen lausepituuteen sekä välimerkkibonukseen; tyhjästä sisällöstä seuraa oletusarvo `0.6`).
- **`drift_dimensions`**: dimensioittainen drift-profiili (`format_adherence`, `fact_accuracy`, `grammar_clarity`). Kokonaisdrift lasketaan näiden pohjalta.

### Rullaavat aggregaatit

Jokaisessa raportissa on avain `rolling_aggregates`, joka sisältää:

- **`total_runs`**: raportoitujen ajokertojen määrä (mukaan lukien nykyinen rivi).
- **`decision_counts`**: hyväksyttyjen/hylättyjen päätösten kumulatiiviset määrät.
- **`moving_averages`**: liukuvat keskiarvot kentille `drift_score`, `fact_accuracy_score`, `grammar_clarity_score` ja `format_violations` koko historian yli.

### JSONL-rivin esimerkkirakenne

```json
{
  "run_id": "...",
  "pipeline": ["IntentioPiiri", "MetodiPiiri", "TarkastusPiiri"],
  "drift_score": 0.08,
  "format_violations": 0,
  "fact_accuracy_score": 0.94,
  "grammar_clarity_score": 0.9,
  "drift_dimensions": {
    "format_adherence": 1,
    "fact_accuracy": 0.94,
    "grammar_clarity": 0.9
  },
  "decision": "accept",
  "hallucination_risk": "low",
  "uncertainty_expressed": false,
  "notes": [/* piirin viestien raakadatat */],
  "rolling_aggregates": {
    "total_runs": 5,
    "decision_counts": {"accept": 4, "revise": 1},
    "moving_averages": {
      "drift_score": 0.12,
      "fact_accuracy_score": 0.9,
      "grammar_clarity_score": 0.88,
      "format_violations": 0.1
    }
  }
}
```
