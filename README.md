# Agent-learning

Moniagenttisen "piiriarkkitehtuurin" v1-MVP, jossa keskitetty PuhemiesAgentti orkestroi kolme sisäistä piiriä ja VarjoAgentti tallentaa juoksukohtaisen analyysin. Toteutus käyttää FastAPI:a ja on paketoitavissa Dockerilla.

## Arkkitehtuurin pääosat

- **PuhemiesAgentti (`SpeakerAgent`)**: ainoa rajapinta käyttäjään. Luodaan `run_id`, reititetään viesti piireihin ja yhdistetään tulokset.
- **Piiri A (Intentio + Konteksti)**: koostaa `TaskSpec`-rakenteen käyttäjän viestistä.
- **Piiri B (Metodi + Tuottaja)**: valitsee metodin tehtävätyypin perusteella (esim. `lesson_v1`, `qa_v1`, `project_plan_v1`, `study_guide_v1`, `design_doc_v1`, `postmortem_v1` tai `comparison_v1`) ja tuottaa sisällön LLM:n avulla. Tarkastuskierros voi ohjata useita revisioita (oletus max 2) ja jokaisesta revisiosta lasketaan osioiden lisäys/muutos -delta.
- **Piiri C (Tarkastaja + Tuomari)**: tarkastaa, että sisältö noudattaa metodia ja antaa päätöksen (accept/revise).
- **VarjoAgentti**: kuuntelee kaikki viestit, laskee monidimensionaalisen drift-scoren (osiopeitto, varoitus- ja revisiopenalty, faktatarkkuus, kielioppi, revisiosyvyys, churn ja driftin nopeus), kasvattaa rullaavia trendejä ja tallentaa JSONL-raportin `data/shadow_reports.jsonl`.

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

   Esimerkkivastaus sisältää nyt revisiohistorian (lisätyt/muokatut osiot numeroiduilla revisioilla), metodivalinnan ja drift-luvut:

   ```json
   {
     "run_id": "...",
     "decision": "accept",
    "summary": "ACCEPT — total revisions: 1; latest added: ['title', 'concept', 'code_example', 'exercise']; latest changed: []; method: lesson_v1 (task_type: lesson_page); drift_score: 0.0; section_completion: 1.0",
     "content": {
       "format": "lesson_v1",
       "title": null,
       "raw": "# Title: Example lesson..."
     },
    "shadow_report_path": "data/shadow_reports.jsonl",
    "revision_summary": {
      "method": "lesson_v1",
      "task_type": "lesson_page",
      "revision_history": [
        {"revision": 0, "added_sections": ["title", "concept", "code_example", "exercise"], "changed_sections": []}
      ]
    }
    }
   ```

### Docker

```bash
docker-compose up --build
```

## Monitorointi ja piiri-nAkymA

- KAynnistA API (esim. `uvicorn app.main:app --reload`) ja avaa `http://localhost:8000/monitor/dashboard` selaimessa: nAet agenttien verkon (User -> PuhemiesAgentti -> piirit) sekA viestien aikaleimat.
- Raakadatan voi hakea JSON-muodossa: `GET /monitor/runs?limit=20` (viimeiset ajot), `GET /monitor/runs/{run_id}`, ja `GET /monitor/graph` (viimeisin graafi + trace).
- Raportit tallennetaan tiedostoon `data/shadow_reports.jsonl`, joten dashboard nAyttAA myAs uudelleenkAynnistyksen jAlkeen kertyneen historian.

### Hybrid kaksipolkuinen ajo (Taoist/Buddhist + itsekAs vertailu)

- Uusi reitti: `POST /chat/hybrid` ottaa `message` (sekA valinnaisesti `energy` ja `hexagram_id`) ja ajaa kahta polkua:
  - **healing**: taoist_core intent -> buddhist_shell stabiloitu vastaus.
  - **selfish**: sama intent, mutta itsekAs kuori testaa palautumista.
- Vastaus sisAltAA `taoist_intent`, `healing_response`, `selfish_response` sekA `verdict`, jonka VarjoAgentti laskee heuristiikalla (rakenne/pituus/selfish-penaltti).
- Esimerkki PowerShellissA:
  ```powershell
  $body = @{ message = "Auttaisitko minua rakentamaan opetusmateriaalin?" } | ConvertTo-Json
  Invoke-RestMethod -Method Post -Uri http://localhost:8000/chat/hybrid -ContentType "application/json" -Body $body
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

- Piiri B valitsee metodin `task_spec.task_type`-kentän perusteella. Oletus on `lesson_page` -> `lesson_v1`; arvot `qa`/`faq` valitsevat mallin `qa_v1` ja `cheatsheet`/`cheat_sheet` valitsevat `cheatsheet_v1`. `howto`/`how_to` ohjautuu `tutorial`-metodiin, `plan`/`project` ohjautuu `project_plan`-metodiin, `study` ohjautuu `study_guide`-metodiin, `design`/`adr`/`architecture` ohjautuvat `design_doc_v1`-metodiin, `post_mortem`/`incident_review`/`retro` ohjautuvat `postmortem_v1`-metodiin ja `versus`/`compare`/`vs` ohjautuvat `comparison_v1`-metodiin.
- `qa_v1`: strukturoitu kysymys-vastaus neljällä osiolla (question, answer, supporting_points, follow_up) ja sisäänrakennettu ohje "Answer first, then provide evidence" + esimerkkiblokki Markdown-rakenteelle.
- `cheatsheet_v1`: tiivis muistilappu (summary, snippets, pitfalls, shortcuts) ohjeella korostaa nopeasti silmäiltävää muotoa sekä esimerkkiblokilla Git-teemasta.
- `project_plan_v1`: toimitussuunnitelma tavoitteille, virstanpylväille, riskeille ja omistajuuksille.
- `study_guide_v1`: tiivis opas ennakkovaatimuksilla, keskeisillä käsitteillä, checkpoint-listalla ja itsearviointikysymyksillä.
- `troubleshooting`, `tutorial` ja `reference` sisältävät edelleen osiokohtaiset skemat. LLM:n promptiin syötetään nyt myös metodikohtaiset esimerkkirakenteet käyttäjän ohjaamiseksi.
- Jos TarkastusPiiri palauttaa `revise`, Puhemies ohjaa lisäkierroksen Piiri B:hen hyödyntäen tarkastusraportin kontekstia. Revisioiden enimmäismäärä voidaan asettaa muuttujalla `MAX_REVISIONS` (oletus 2), ja jokaisesta kierroksesta tallennetaan lisätyt ja muuttuneet osiot `revision_history`-listaan sekä käyttäjäsummaryyn.

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

- **`drift_score`**: koostuu osiopeiton aukosta, varoituspenaltysta, revisio- ja churn-penaltysta sekä faktatarkkuuden ja kieliopin puutteista ja driftin nopeudesta.
- **`drift_dimensions`**: dimensioittainen profiili (format_adherence, coverage_gap, warning_pressure, revision_pressure, fact_accuracy, grammar_clarity, revision_depth, section_completion, revision_churn, drift_velocity, coverage_trend).
- **`fact_accuracy_score`** ja **`grammar_clarity_score`** säilyvät mutta vaikuttavat nyt kokonaisdriftiin.
- **`section_completion_rate`** ja revisiosyvyys (`revision_depth`) lisätään metriikoihin, jolloin raportti heijastaa myös osiotason valmiutta.
- **`acceptance_rate`** seurataan rullaavasti, jolloin kokonaislaadun kehitystä on helpompi tulkita.
- **`revision_history`** tallennetaan jokaiselle riville (lisätyt/muokatut osiot per kierros) ja snapshot viimeisistä revisioista, jolloin käyttäjäpalautteen delta vastaa varjoraporttia.

### Rullaavat aggregaatit ja trendit

Jokaisessa raportissa on avain `rolling_aggregates`, joka sisältää:

- **`total_runs`**: raportoitujen ajokertojen määrä (mukaan lukien nykyinen rivi).
- **`decision_counts`**: hyväksyttyjen/hylättyjen päätösten kumulatiiviset määrät.
- **`rolling_averages`**: 5 edellisen ajon liukuvat keskiarvot kentille `drift_score`, `fact_accuracy_score`, `grammar_clarity_score`, `format_violations`, `section_coverage`, `section_completion_rate`, `revision_depth` ja `acceptance_rate`.
- **`historical_trends`**: viimeisten 5 ajon min/max-arvot, sparklines ja delta nykyhetken ja ikkunan alun välillä samoille mittareille.

### JSONL-rivin esimerkkirakenne

```json
{
  "run_id": "...",
  "pipeline": ["IntentioPiiri", "MetodiPiiri", "TarkastusPiiri"],
  "drift_score": 0.08,
  "format_violations": 0,
  "fact_accuracy_score": 0.94,
  "grammar_clarity_score": 0.9,
  "section_completion_rate": 1.0,
  "revision_depth": 1,
  "revision_churn": 3,
  "drift_dimensions": {
    "format_adherence": 1,
    "fact_accuracy": 0.94,
    "grammar_clarity": 0.9,
    "revision_depth": 1,
    "section_completion": 1.0,
    "revision_churn": 3,
    "drift_velocity": 0.02,
    "coverage_trend": 0.01
  },
  "decision": "accept",
  "hallucination_risk": "low",
  "uncertainty_expressed": false,
  "acceptance_rate": 0.8,
  "revision_history": [
    {"revision": 0, "added_sections": ["title", "concept"], "changed_sections": []},
    {"revision": 1, "added_sections": ["code_example", "exercise"], "changed_sections": ["concept"]}
  ],
  "revision_history_snapshot": [{"revision": 1, "added_sections": ["code_example", "exercise"], "changed_sections": ["concept"]}],
  "notes": [/* piirin viestien raakadatat */],
  "rolling_aggregates": {
    "total_runs": 5,
    "decision_counts": {"accept": 4, "revise": 1},
    "rolling_averages": {
      "drift_score": 0.12,
      "fact_accuracy_score": 0.9,
      "grammar_clarity_score": 0.88,
      "format_violations": 0.1,
      "section_completion_rate": 0.92,
      "revision_depth": 1.2,
      "acceptance_rate": 0.78
    }
  },
  "historical_trends": {
    "drift_score": {"delta": 0.04, "min": 0.08, "max": 0.12, "spark": [0.08, 0.09, 0.1, 0.11, 0.12]},
    "section_completion_rate": {"delta": 0.07, "min": 0.85, "max": 0.92, "spark": [0.85, 0.88, 0.9, 0.91, 0.92]}
  }
}
```

## Hybrid kaksipolkuinen ajo (Taoist/Buddhist + itsekAs vertailu)

- Uusi reitti: `POST /chat/hybrid` ottaa `message` (sekA valinnaisesti `energy` ja `hexagram_id`) ja ajaa kahta polkua:
  - **healing**: taoist_core intent -> buddhist_shell stabiloitu vastaus.
  - **selfish**: sama intent, mutta itsekAs kuori testaa palautumista.
- Vastaus sisAltAA `taoist_intent`, `healing_response`, `selfish_response` sekA `verdict`, jonka VarjoAgentti laskee heuristiikalla (rakenne/pituus/selfish-penaltti).
- Esimerkki PowerShellissA:
  ```powershell
  $body = @{ message = "Auttaisitko minua rakentamaan opetusmateriaalin?" } | ConvertTo-Json
  Invoke-RestMethod -Method Post -Uri http://localhost:8000/chat/hybrid -ContentType "application/json" -Body $body
  ```

## Puhemies-sivu (tAysi hierarkia)

- Selaimessa `http://localhost:8000/puhemies` voit keskustella suoraan puhemiehen kanssa; se kutsuu /chat/hybrid ja nAyttAA taoist-intentin, healing- ja selfish-vastaukset sekA verdictin.

## Suggested English test prompts

- Mental math with utility tips: "Compute 17 * 23 in your head and give two tips for mental multiplication."
- Estimation without tools: "Give two ways to approximate the square root of 50 without a calculator."
- Safety/utility checklist: "Give a short checklist for running outside in freezing weather."
- Grounding-required (no live data): "What is the current EUR/USD rate right now?" (expect honest limitation + how to check; no fabricated numbers).
