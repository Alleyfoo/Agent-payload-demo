# Agent-learning

Moniagenttisen "piiriarkkitehtuurin" v1-MVP, jossa keskitetty PuhemiesAgentti orkestroi kolme sisäistä piiriä ja VarjoAgentti tallentaa juoksukohtaisen analyysin. Toteutus käyttää FastAPI:a ja on paketoitavissa Dockerilla.

## Arkkitehtuurin pääosat

- **PuhemiesAgentti (`SpeakerAgent`)**: ainoa rajapinta käyttäjään. Luodaan `run_id`, reititetään viesti piireihin ja yhdistetään tulokset.
- **Piiri A (Intentio + Konteksti)**: koostaa `TaskSpec`-rakenteen käyttäjän viestistä.
- **Piiri B (Metodi + Tuottaja)**: valitsee metodin tehtävätyypin perusteella (esim. `lesson_v1`, `qa_v1` tai `cheatsheet_v1`) ja tuottaa sisällön LLM:n avulla. Tarkastuskierros voi ohjata useita revisioita (oletus max 2) ja jokaisesta revisiosta lasketaan osioiden lisäys/muutos -delta.
- **Piiri C (Tarkastaja + Tuomari)**: tarkastaa, että sisältö noudattaa metodia ja antaa päätöksen (accept/revise).
- **VarjoAgentti**: kuuntelee kaikki viestit, laskee monidimensionaalisen drift-scoren (osiopeitto, varoitus- ja revisiopenalty, faktatarkkuus, kielioppi), kasvattaa rullaavia trendejä ja tallentaa JSONL-raportin `data/shadow_reports.jsonl`.

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

   Esimerkkivastaus sisältää nyt revisiohistorian (lisätyt/muokatut osiot) ja drift-luvut:

   ```json
   {
     "run_id": "...",
     "decision": "accept",
    "summary": "ACCEPT — revisions: 1; added: ['title', 'concept', 'code_example', 'exercise']; changed: []; drift_score: 0.0",
     "content": {
       "format": "lesson_v1",
       "title": null,
       "raw": "# Title: Example lesson..."
     },
     "shadow_report_path": "data/shadow_reports.jsonl"
   }
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
- `app/agents/shadow.py`: VarjoAgentin lokitus ja analyysi
- `app/utils/llm_client.py`: Ollama-kutsu tai mock
- `data/`: VarjoAgentin raportit (JSONL)

### Metodivalinta ja revisiot

- Piiri B valitsee metodin `task_spec.task_type`-kentän perusteella. Oletus on `lesson_page` -> `lesson_v1`; arvo `qa` valitsee mallin `qa_v1` ja `cheatsheet` valitsee `cheatsheet_v1`.
- `qa_v1`: strukturoitu kysymys-vastaus neljällä osiolla (question, answer, supporting_points, follow_up) ja sisäänrakennettu ohje "Answer first, then provide evidence" + esimerkkiblokki Markdown-rakenteelle.
- `cheatsheet_v1`: tiivis muistilappu (summary, snippets, pitfalls, shortcuts) ohjeella korostaa nopeasti silmäiltävää muotoa sekä esimerkkiblokilla Git-teemasta.
- `troubleshooting`, `tutorial` ja `reference` sisältävät edelleen osiokohtaiset skemat. LLM:n promptiin syötetään nyt myös metodikohtaiset esimerkkirakenteet käyttäjän ohjaamiseksi.
- Jos TarkastusPiiri palauttaa `revise`, Puhemies ohjaa lisäkierroksen Piiri B:hen hyödyntäen tarkastusraportin kontekstia. Revisioiden enimmäismäärä voidaan asettaa muuttujalla `MAX_REVISIONS` (oletus 2), ja jokaisesta kierroksesta tallennetaan lisätyt ja muuttuneet osiot `revision_history`-listaan sekä käyttäjäsummaryyn.

## Jatkokehitysideoita

- Pitkän aikavälin drift-trendien visualisointi (esim. viikkotason graafit)
- Päätösten (accept/revise) parempi perustelu käyttäjäviestissä
- API-rajapinnan rikastaminen palauttamalla myös VarjoAgentin rullaavat trendit

## Tehtävätyypit ja metodit

PuhemiesAgentti ohjaa MetodiPiiriin tehtävätyypin (`task_type`) perusteella, jolloin sisällöntuotannon metodi ja osiot vaihtuvat. Tuetut tyypit:

- `lesson_page`: lyhyt teoria + harjoitus (osiot: title, concept, code_example, exercise)
- `tutorial`: askel-askeleelta -ohje käytännön tavoitteeseen (title, overview, steps, validation, next_steps)
- `reference`: tiivis muistilappu syntaksista ja optioista (summary, api_surface, usage_examples, caveats)
- `troubleshooting`: vianmääritys ja korjauspolku (issue_summary, root_causes, diagnostic_steps, fixes, prevention)

### Esimerkkipayloadit

LLM:lle rakentuva `TaskSpec`-rakenne näyttää tältä (kentät täytetään IntentioPiirissä):

```json
{
  "task_type": "tutorial",
  "topic": "Docker-kontin rakentaminen Python-sovellukselle",
  "language": "fi",
  "target_level": "intermediate",
  "constraints": ["markdown output", "sisällytä komennot"]
}
```

Vastaavasti vianmääritykseen voidaan käyttää `troubleshooting`-tyyppiä:

```json
{
  "task_type": "troubleshooting",
  "topic": "FastAPI sovellus palauttaa 500-virheen kun tietokanta ei vastaa",
  "language": "fi",
  "target_level": "advanced",
  "constraints": ["listaa tarkistuskomennot", "lyhyet korjausvaiheet"]
}
```

## VarjoAgentin raportointi ja metriikat

VarjoAgentti kerää jokaisesta ajosta sekä juoksukohtaiset mitat että kumulatiiviset aggregaatit ja kirjoittaa ne JSONL-riviin tiedostoon `data/shadow_reports.jsonl`.

### Päivitetyt mittarit

- **`drift_score`**: koostuu osiopeiton aukosta, varoituspenaltysta, revisiopenaltysta sekä faktatarkkuuden ja kieliopin puutteista.
- **`drift_dimensions`**: dimensioittainen profiili (format_adherence, coverage_gap, warning_pressure, revision_pressure, fact_accuracy, grammar_clarity).
- **`fact_accuracy_score`** ja **`grammar_clarity_score`** säilyvät mutta vaikuttavat nyt kokonaisdriftiin.
- **`revision_history`** tallennetaan jokaiselle riville (lisätyt/muokatut osiot per kierros), jolloin käyttäjäpalautteen delta vastaa varjoraporttia.

### Rullaavat aggregaatit ja trendit

Jokaisessa raportissa on avain `rolling_aggregates`, joka sisältää:

- **`total_runs`**: raportoitujen ajokertojen määrä (mukaan lukien nykyinen rivi).
- **`decision_counts`**: hyväksyttyjen/hylättyjen päätösten kumulatiiviset määrät.
- **`rolling_averages`**: 5 edellisen ajon liukuvat keskiarvot kentille `drift_score`, `fact_accuracy_score`, `grammar_clarity_score`, `format_violations` ja `section_coverage`.
- **`rolling_trends`**: viimeisimmän ja sitä edeltävän ajon eroavaisuudet keskeisissä mittareissa.

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
