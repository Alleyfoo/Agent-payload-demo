# Agent-learning

Moniagenttisen "piiriarkkitehtuurin" v1-MVP, jossa keskitetty PuhemiesAgentti orkestroi kolme sisäistä piiriä ja VarjoAgentti tallentaa juoksukohtaisen analyysin. Toteutus käyttää FastAPI:a ja on paketoitavissa Dockerilla.

## Arkkitehtuurin pääosat

- **PuhemiesAgentti (`SpeakerAgent`)**: ainoa rajapinta käyttäjään. Luodaan `run_id`, reititetään viesti piireihin ja yhdistetään tulokset.
- **Piiri A (Intentio + Konteksti)**: koostaa `TaskSpec`-rakenteen käyttäjän viestistä.
- **Piiri B (Metodi + Tuottaja)**: valitsee metodin tehtävätyypin perusteella (esim. `lesson_v1` tai `qa_v1`) ja tuottaa sisällön LLM:n avulla. Jos tarkastuspyyntö vaatii korjausta, piiri tuottaa yhden iteratiivisen revisiokierroksen.
- **Piiri C (Tarkastaja + Tuomari)**: tarkastaa, että sisältö noudattaa metodia ja antaa päätöksen (accept/revise).
- **VarjoAgentti**: kuuntelee kaikki viestit, laskee drift-scoren (osiopeitto + varoitukset), kasvattaa historiatason metriikoita ja tallentaa JSONL-raportin `data/shadow_reports.jsonl`.

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
- `app/agents/shadow.py`: VarjoAgentin lokitus ja analyysi
- `app/utils/llm_client.py`: Ollama-kutsu tai mock
- `data/`: VarjoAgentin raportit (JSONL)

### Metodivalinta ja revisiot

- Piiri B valitsee metodin `task_spec.task_type`-kentän perusteella. Oletus on `lesson_page` -> `lesson_v1`; arvo `qa` valitsee mallin `qa_v1` (osiot: question, answer, follow_up) ja `cheatsheet` valitsee `cheatsheet_v1` (summary, snippets, pitfalls, shortcuts).
- Jos TarkastusPiiri palauttaa `revise`, Puhemies ohjaa lisäkierroksen Piiri B:hen hyödyntäen tarkastusraportin puuttuvia osioita. Revisioiden enimmäismäärä voidaan asettaa muuttujalla `MAX_REVISIONS` (oletus 2).
- VarjoAgentti kerää jokaisesta ajosta drift-scoren (osiopeitto + varoituskerroin + revisiokertoimien pieni lisä) sekä yksinkertaisen historiatiivisteen (keskimääräinen drift, viimeisimmät formaattivirheet).

## Jatkokehitysideoita

- Laajenna metodikirjastoa tehtävätyyppikohtaisilla ohjeilla ja esimerkeillä
- Raskautetut drift-metriikat (esim. sisältötarkkuus, kielivirheet) ja pidemmän aikavälin trendit
- Revisiosilmukan kontekstin tallennus (esim. muuttuneet osiot) ja näkyvyys käyttäjän palautteessa
