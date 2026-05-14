# AI-Powered PIDS PWA Prototype

Backend-powered Progressive Web App prototype for MRT Kajang / Kwasa Damansara Line passenger information displays. The frontend is a React/Vite app served by FastAPI after build.

## Views

- `/concourse` shows upcoming trains for Platform 1 and Platform 2 with CDA and AI advisory.
- `/platform` shows the first arriving train, four-coach load CDA, recommended coach, and travel advisory.
- `/classic` shows a fullscreen HD legacy-style board with live Platform, Train, Destination, Time, current time, and current date values.
- `/coach-load` shows fullscreen coach load colors using the next train's AI coach occupancy.

There is no on-screen mode switch. Each display is selected by URL so kiosk screens can be pinned to one mode.

## Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install
npm run build
.venv/bin/python -m uvicorn backend:app --host 127.0.0.1 --port 4173
```

Then open:

```text
http://localhost:4173/concourse
http://localhost:4173/platform
http://localhost:4173/classic
http://localhost:4173/coach-load
```

Swagger / OpenAPI docs:

```text
http://localhost:4173/docs
```

The service worker and manifest make the app installable when served over localhost or HTTPS. The PWA uses network-first caching and polls the live display API every 5 seconds.

## Backend API

- `GET /api/health` shows backend status, configured model, and whether OpenAI is enabled.
- `GET /api/stations` returns scalable station/platform configuration.
- `GET /api/display/{station_id}` returns live AI-backed display frames for all station platforms.
- `GET /api/display/{station_id}/platform/{platform_id}` returns one platform display frame.
- `POST /api/ai/advisory` accepts an ad-hoc frame context and returns CDA/advisory output.

For testing an arrived train state:

```text
http://localhost:4173/api/display/kg16?force_arrived=true
```

That returns `arrivalStatus: "arrived"`, `arrivalLabel: "NOW"`, and `service: "Boarding Now"` for the first train on each platform.

The schedule frame generator follows the proposed MRT Kajang Line headways:

- Weekday peak, 7:00 AM-9:00 AM and 5:00 PM-7:00 PM: 5 to 6 minutes.
- Weekday off-peak, 9:00 AM-5:00 PM and 7:00 PM-12:00 AM: 10 minutes.
- Weekends and public holidays: 10 minutes.
- Operating hours: 6:00 AM to 11:30 PM, with last train departing from terminal stations.

Each API response includes `generatedAt`, `generatedAtDisplay`, `servicePeriod`, `isOperating`, `refreshAfterSeconds`, train ETAs, CDA values, coach loads, recommended coach, and advisory text.

## OpenAI Setup

This prototype now requires an OpenAI key for display data. Edit `.env`:

```bash
OPENAI_API_KEY=sk-proj-your-key-here
OPENAI_MODEL=gpt-5.4
ENABLE_OPENAI_CDA=true
AI_CACHE_SECONDS=60
```

When `OPENAI_API_KEY` is missing, `/api/display/{station_id}` returns `503` and the PWA shows an OpenAI-key-required screen. The deterministic rule engine is only used as input context for the AI prompt, not as a public fallback display mode.

## Prototype AI Workflow

The prompt workflow is in `prompts/cda-travel-advisory.md`. The backend output shape is:

```json
{
  "crowdDensity": 56,
  "coaches": [
    { "coach": 1, "load": 78 },
    { "coach": 2, "load": 56 },
    { "coach": 3, "load": 34 },
    { "coach": 4, "load": 49 }
  ],
  "advisory": "Board Coach 3 for lower crowd density and smoother boarding."
}
```
