from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - handled at runtime for lightweight demos
    OpenAI = None


ROOT = Path(__file__).parent
NETWORK_PATH = ROOT / "data" / "network.json"
DIST_ROOT = ROOT / "dist"
load_dotenv(ROOT / ".env")

TIMEZONE = ZoneInfo(os.getenv("PIDS_TIMEZONE", "Asia/Kuala_Lumpur"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4")
ENABLE_OPENAI_CDA = os.getenv("ENABLE_OPENAI_CDA", "true").lower() == "true"
AI_CACHE_SECONDS = int(os.getenv("AI_CACHE_SECONDS", "60"))

app = FastAPI(
    title="AI MRT PIDS Prototype API",
    version="0.2.0",
    description="FastAPI backend for live mock MRT Kajang Line PIDS frames with optional OpenAI CDA/advisory generation.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ai_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def require_openai_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is required. Set it in .env and restart the backend.",
        )
    if OpenAI is None:
        raise HTTPException(status_code=503, detail="OpenAI SDK is not installed.")
    if not ENABLE_OPENAI_CDA:
        raise HTTPException(status_code=503, detail="ENABLE_OPENAI_CDA must be true for AI display mode.")


class CoachLoad(BaseModel):
    coach: int = Field(ge=1, le=4)
    load: int = Field(ge=0, le=100)


class AiFrame(BaseModel):
    crowdDensity: int = Field(ge=0, le=100)
    crowdCondition: str
    passengerFlow: str
    coaches: list[CoachLoad] = Field(min_length=4, max_length=4)
    recommendedCoach: int = Field(ge=1, le=4)
    advisory: str = Field(min_length=4, max_length=120)
    platformAdvisory: str = Field(min_length=4, max_length=160)


def load_network() -> dict[str, Any]:
    return json.loads(NETWORK_PATH.read_text())


def parse_hhmm(value: str) -> day_time:
    hour, minute = value.split(":")
    return day_time(int(hour), int(minute))


def in_window(now: datetime, start: str, end: str) -> bool:
    current = now.time()
    start_time = parse_hhmm(start)
    if end == "24:00":
      return current >= start_time
    return start_time <= current < parse_hhmm(end)


def service_period(now: datetime, network: dict[str, Any]) -> tuple[str, list[int]]:
    headways = network["line"]["headways"]
    if now.weekday() >= 5:
        return "Weekend / Public Holiday", headways["weekendPublicHoliday"]["minutes"]

    for start, end in headways["weekdayPeak"]["periods"]:
        if in_window(now, start, end):
            return "Weekday Peak", headways["weekdayPeak"]["minutes"]

    return "Weekday Off-Peak", headways["weekdayOffPeak"]["minutes"]


def is_operating(now: datetime, network: dict[str, Any]) -> bool:
    hours = network["line"]["operatingHours"]
    current = now.time()
    return parse_hhmm(hours["firstTrain"]) <= current <= parse_hhmm(hours["lastDepartureFromTerminal"])


def find_station(network: dict[str, Any], station_id: str) -> dict[str, Any]:
    for station in network["stations"]:
        if station["id"] == station_id:
            return station
    raise HTTPException(status_code=404, detail=f"Unknown station: {station_id}")


def deterministic_rng(*parts: Any) -> random.Random:
    seed = "|".join(str(part) for part in parts)
    return random.Random(seed)


def cda_label(value: int) -> str:
    if value >= 85:
        return "Very High"
    if value >= 70:
        return "High"
    if value >= 45:
        return "Medium"
    return "Low"


def passenger_flow(value: int) -> str:
    if value >= 78:
        return "Congested"
    if value >= 45:
        return "Moderate"
    return "Smooth"


def train_id(prefix: str, now: datetime, platform_index: int, train_index: int) -> str:
    service_number = ((now.hour * 60 + now.minute) // 5 + platform_index * 7 + train_index * 4) % 900
    return f"{prefix}{100 + service_number:03d}"


def arrival_state(arrival_mins: int, operating: bool) -> dict[str, Any]:
    if not operating:
        return {
            "arrivalStatus": "not_operating",
            "arrivalLabel": "--",
            "arrivalUnit": "service resumes",
            "isArrived": False,
        }
    if arrival_mins <= 0:
        return {
            "arrivalStatus": "arrived",
            "arrivalLabel": "NOW",
            "arrivalUnit": "arrived",
            "isArrived": True,
        }
    if arrival_mins == 1:
        return {
            "arrivalStatus": "arriving",
            "arrivalLabel": "1",
            "arrivalUnit": "min arriving",
            "isArrived": False,
        }
    return {
        "arrivalStatus": "scheduled",
        "arrivalLabel": str(arrival_mins),
        "arrivalUnit": "min",
        "isArrived": False,
    }


def build_fallback_ai(
    station: dict[str, Any],
    platform: dict[str, Any],
    arrival_mins: int,
    period: str,
    generated_at: datetime,
    train_index: int,
) -> dict[str, Any]:
    rng = deterministic_rng(station["id"], platform["id"], generated_at.strftime("%Y%m%d%H%M"), train_index)
    base = 64 if period == "Weekday Peak" else 42
    if arrival_mins <= 3:
        base += 8
    crowd_density = max(18, min(94, base + rng.randint(-14, 16)))
    coaches = []
    for coach in range(1, 5):
        platform_bias = -8 if coach in (2, 3) else 8
        load = max(12, min(96, crowd_density + platform_bias + rng.randint(-18, 18)))
        coaches.append({"coach": coach, "load": load})

    recommended = min(coaches, key=lambda item: item["load"])
    flow = passenger_flow(crowd_density)
    advisory = f"Proceed to {platform['name']}. Board Coach {recommended['coach']} for lower crowd density."
    platform_advisory = (
        f"Board Coach {recommended['coach']}. Move along the platform for smoother boarding."
        if flow != "Smooth"
        else f"Board Coach {recommended['coach']} for the smoothest entry."
    )
    return {
        "crowdDensity": crowd_density,
        "crowdCondition": cda_label(crowd_density),
        "passengerFlow": flow,
        "coaches": coaches,
        "recommendedCoach": recommended["coach"],
        "advisory": advisory,
        "platformAdvisory": platform_advisory,
        "source": "mock-rule-engine",
    }


def extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("AI response did not contain JSON")
    return json.loads(match.group(0))


def openai_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY")) and OpenAI is not None and ENABLE_OPENAI_CDA


def generate_openai_ai(
    station: dict[str, Any],
    platform: dict[str, Any],
    arrival_mins: int,
    period: str,
    generated_at: datetime,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    cache_key = f"{station['id']}:{platform['id']}:{arrival_mins}:{period}:{generated_at.strftime('%Y%m%d%H%M')}"
    cached = _ai_cache.get(cache_key)
    if cached and time.time() - cached[0] < AI_CACHE_SECONDS:
        return cached[1]

    require_openai_key()

    prompt = {
        "station": station["name"],
        "platform": platform["name"],
        "direction": platform["direction"],
        "arrivalMins": arrival_mins,
        "servicePeriod": period,
        "fallbackEstimate": fallback,
        "instruction": "Return JSON only using passenger-safe wording for MRT signage.",
    }
    client = OpenAI()
    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=(
            "You generate Crowd Density Analysis and passenger travel advisories for MRT signage. "
            "Return JSON only with keys: crowdDensity, crowdCondition, passengerFlow, coaches, "
            "recommendedCoach, advisory, platformAdvisory. Keep advisories short and operational."
        ),
        input=json.dumps(prompt),
        reasoning={"effort": "low"},
    )
    parsed = extract_json(response.output_text)
    validated = AiFrame.model_validate(parsed).model_dump()
    validated["source"] = f"openai:{OPENAI_MODEL}"
    _ai_cache[cache_key] = (time.time(), validated)
    return validated


def train_frame(
    station: dict[str, Any],
    platform: dict[str, Any],
    platform_index: int,
    train_index: int,
    now: datetime,
    headway: int,
    period: str,
    operating: bool,
    force_arrived: bool = False,
) -> dict[str, Any]:
    offset = ((platform_index + 1) * 2 + now.minute) % headway
    arrival_mins = 0 if not operating else headway * train_index + offset
    if force_arrived and train_index == 0:
        arrival_mins = 0
    fallback = build_fallback_ai(station, platform, arrival_mins, period, now, train_index)
    ai = generate_openai_ai(station, platform, arrival_mins, period, now, fallback)
    arrival_time = now + timedelta(minutes=arrival_mins)
    service = "Normal Service" if operating else "Service resumes 06:00"
    if operating and arrival_mins <= 0:
        service = "Boarding Now"
    return {
        "id": train_id(platform["trainPrefix"], now, platform_index, train_index),
        "destination": platform["terminal"],
        "arrivalMins": arrival_mins,
        "arrivalTime": arrival_time.isoformat(),
        "service": service,
        **arrival_state(arrival_mins, operating),
        "crowdDensity": ai["crowdDensity"],
        "crowdCondition": ai["crowdCondition"],
        "passengerFlow": ai["passengerFlow"],
        "advisory": ai["advisory"],
        "platformAdvisory": ai["platformAdvisory"],
        "recommendedCoach": ai["recommendedCoach"],
        "coaches": ai["coaches"],
        "aiSource": ai.get("source", "openai"),
    }


def build_display(station_id: str, force_arrived: bool = False) -> dict[str, Any]:
    require_openai_key()
    network = load_network()
    station = find_station(network, station_id)
    now = datetime.now(TIMEZONE)
    period, headway_options = service_period(now, network)
    operating = is_operating(now, network)

    platforms = []
    for platform_index, platform in enumerate(station["platforms"]):
        trains = []
        for train_index in range(3):
            headway = headway_options[(now.minute + train_index + platform_index) % len(headway_options)]
            trains.append(
                train_frame(
                    station,
                    platform,
                    platform_index,
                    train_index,
                    now,
                    headway,
                    period,
                    operating,
                    force_arrived=force_arrived,
                )
            )
        platforms.append({**platform, "trains": trains})

    return {
        "line": network["line"],
        "station": {
            "id": station["id"],
            "code": station["code"],
            "name": station["name"],
        },
        "generatedAt": now.isoformat(),
        "generatedAtDisplay": now.strftime("%d %b %Y, %H:%M:%S"),
        "timezone": str(TIMEZONE),
        "servicePeriod": period,
        "isOperating": operating,
        "refreshAfterSeconds": 15,
        "platforms": platforms,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": openai_available(),
        "generatedAt": datetime.now(TIMEZONE).isoformat(),
        "openaiEnabled": openai_available(),
        "model": OPENAI_MODEL,
        "requiresOpenAIKey": True,
    }


@app.get("/api/stations")
def stations() -> dict[str, Any]:
    network = load_network()
    return {"line": network["line"], "stations": network["stations"]}


@app.get("/api/display/{station_id}")
def display(
    station_id: str = os.getenv("PIDS_STATION_ID", "kg16"),
    force_arrived: bool = Query(False, description="Force first train on each platform to show NOW for demo testing."),
) -> dict[str, Any]:
    return build_display(station_id, force_arrived=force_arrived)


@app.get("/api/display/{station_id}/platform/{platform_id}")
def platform_display(station_id: str, platform_id: str) -> dict[str, Any]:
    display_data = build_display(station_id)
    for platform in display_data["platforms"]:
        if platform["id"] == platform_id:
            return {**display_data, "platforms": [platform]}
    raise HTTPException(status_code=404, detail=f"Unknown platform: {platform_id}")


@app.post("/api/ai/advisory", response_model=AiFrame)
def ai_advisory(payload: dict[str, Any]) -> dict[str, Any]:
    station = {"id": payload.get("stationId", "ad-hoc"), "name": payload.get("station", "MRT Station")}
    platform = {
        "id": payload.get("platformId", "p1"),
        "name": payload.get("platform", "Platform 1"),
        "direction": payload.get("direction", "Toward Kwasa Damansara"),
    }
    now = datetime.now(TIMEZONE)
    fallback = build_fallback_ai(station, platform, int(payload.get("arrivalMins", 5)), "Weekday Peak", now, 0)
    return generate_openai_ai(station, platform, int(payload.get("arrivalMins", 5)), payload.get("servicePeriod", "Weekday Peak"), now, fallback)


app.mount("/data", StaticFiles(directory=ROOT / "data"), name="data")
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")
if (DIST_ROOT / "assets").exists():
    app.mount("/dist-assets", StaticFiles(directory=DIST_ROOT / "assets"), name="dist-assets")


@app.get("/")
def index() -> FileResponse:
    if (DIST_ROOT / "index.html").exists():
        return FileResponse(DIST_ROOT / "index.html")
    return FileResponse(ROOT / "index.html")


@app.get("/{path:path}")
def static_files(path: str) -> FileResponse:
    dist_target = DIST_ROOT / path
    if dist_target.is_file():
        return FileResponse(dist_target)
    target = ROOT / path
    if target.is_file() and target.parent == ROOT:
        return FileResponse(target)
    if (DIST_ROOT / "index.html").exists():
        return FileResponse(DIST_ROOT / "index.html")
    return FileResponse(ROOT / "index.html")
