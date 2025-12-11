# Agent-learning

Moniagenttisen "piiriarkkitehtuurin" v1-MVP, jossa keskitetty PuhemiesAgentti orkestroi kolme sisäistä piiriä ja VarjoAgentti tallentaa juoksukohtaisen analyysin. Toteutus käyttää FastAPI:a ja on paketoitavissa Dockerilla.

## Arkkitehtuurin pääosat

- **PuhemiesAgentti (`SpeakerAgent`)**: ainoa rajapinta käyttäjään. Luodaan `run_id`, reititetään viesti piireihin ja yhdistetään tulokset.
- **Piiri A (Intentio + Konteksti)**: koostaa `TaskSpec`-rakenteen käyttäjän viestistä.
- **Piiri B (Metodi + Tuottaja)**: määrittää oletusmetodin (`lesson_v1`) ja tuottaa sisällön LLM:n avulla.
- **Piiri C (Tarkastaja + Tuomari)**: tarkastaa, että sisältö noudattaa metodia ja antaa päätöksen (accept/revise).
- **VarjoAgentti**: kuuntelee kaikki viestit, laskee yksinkertaisen drift-scoren ja tallentaa JSONL-raportin `data/shadow_reports.jsonl`.

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

## Jatkokehitysideoita

- Iteratiivinen revise-kierros Piiri B:n kanssa
- Useamman metodimallin tuki
- Tarkempia drift-metriikoita ja historiatason analyysiä
