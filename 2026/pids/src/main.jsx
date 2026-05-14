import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";

const STATION_ID = "kg16";

function cdaClass(value) {
  if (value >= 85) return "critical";
  if (value >= 70) return "high";
  if (value >= 45) return "medium";
  return "low";
}

function cdaLabel(value) {
  if (value >= 85) return "Very High";
  if (value >= 70) return "High";
  if (value >= 45) return "Medium";
  return "Low";
}

function coachDescription(load, recommended) {
  if (recommended) return <>Low load<br />Recommended</>;
  if (load >= 85) return <>Very high load<br />Use another coach</>;
  if (load >= 70) return <>High load<br />Avoid if possible</>;
  if (load >= 45) return <>Medium load<br />Acceptable</>;
  return <>Low load<br />Smooth boarding</>;
}

function formatTime(value, seconds = false) {
  if (!value) return "--:--";
  return new Date(value).toLocaleTimeString("en-MY", {
    hour: "2-digit",
    minute: "2-digit",
    second: seconds ? "2-digit" : undefined,
    hour12: false,
  });
}

function formatDate(value) {
  const date = value ? new Date(value) : new Date();
  return date.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function timeLabel(train) {
  if (train.arrivalStatus === "arrived" || train.isArrived) return "NOW";
  return `${train.arrivalLabel || train.arrivalMins} Min`;
}

function uppercaseWords(value) {
  return String(value).toUpperCase();
}

function currentMode() {
  const path = window.location.pathname.replace("/", "");
  const hash = window.location.hash.replace("#", "");
  const mode = path || hash || "classic";
  return ["concourse", "platform", "classic", "coach-load"].includes(mode) ? mode : "classic";
}

function useClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

function useDisplayData() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  async function loadData() {
    try {
      const response = await fetch(`/api/display/${STATION_ID}`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `API returned ${response.status}`);
      setData(payload);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    loadData();
    const timer = window.setInterval(loadData, 5000);
    return () => window.clearInterval(timer);
  }, []);

  return { data, error };
}

function Arrival({ train, sizeClass = "" }) {
  const arrived = train.arrivalStatus === "arrived" || train.isArrived;
  const label = train.arrivalLabel || String(train.arrivalMins);
  const unit = train.arrivalUnit || "min";
  return (
    <>
      <div className={`${sizeClass} ${arrived ? "now" : ""}`}>{label}</div>
      <div className={`${sizeClass === "small-mins" ? "small-label" : "min-label"} ${arrived ? "now-label" : ""}`}>
        {unit}
      </div>
    </>
  );
}

function TrainCard({ train, latest = false }) {
  const cda = train.crowdCondition || cdaLabel(train.crowdDensity);
  const klass = cdaClass(train.crowdDensity);
  return (
    <div className={`train-card ${latest ? "latest" : ""}`}>
      <div className="train-main">
        <div className="train-no">{train.id}</div>
        <div className="train-meta">
          {latest ? "Next train" : "4 coaches"} · {train.service} · ETA {formatTime(train.arrivalTime)}
        </div>
      </div>
      <div className="arrival">
        <Arrival train={train} sizeClass="mins" />
      </div>
      {latest && (
        <div className="insight-row">
          <div className="insight cda">
            <div className="insight-label">CDA</div>
            <div className={`insight-value ${klass}`}>{cda}</div>
          </div>
          <div className="insight ai">
            <div className="insight-label">AI Recommendation · {train.aiSource || "openai"}</div>
            <div className="ai-text">{train.advisory}</div>
          </div>
        </div>
      )}
    </div>
  );
}

function Header({ title, subtitle, data, error, now }) {
  return (
    <header className="topbar">
      <div className="title">
        <h1>{title}</h1>
        <p>{subtitle}</p>
        <div className="live-meta">
          <span>{data.station?.code} {data.station?.name}</span>
          <span>{data.servicePeriod}</span>
          <span>Updated {data.generatedAtDisplay}</span>
          <span className={error ? "warn" : ""}>{error ? "AI API unavailable" : "Live AI API"}</span>
        </div>
      </div>
      <div className="clock">{formatTime(now)}</div>
    </header>
  );
}

function Concourse({ data, error, now }) {
  return (
    <section className="display concourse">
      <Header
        title={`${data.line?.name || "MRT Kajang Line"} Concourse PIDS`}
        subtitle="Upcoming trains · Crowd Density Analysis · AI passenger recommendation"
        data={data}
        error={error}
        now={now}
      />
      <section className="platform-grid">
        {data.platforms.map((platform, index) => (
          <article className="platform-panel" key={platform.id}>
            <header className="platform-head">
              <div>
                <div className="platform-label">{platform.name}</div>
                <div className={`destination ${index === 0 ? "p1" : "p2"}`}>{platform.direction}</div>
              </div>
              <div className="tag">Concourse View</div>
            </header>
            <div className="train-list">
              {platform.trains.map((train, trainIndex) => (
                <TrainCard key={train.id} train={train} latest={trainIndex === 0} />
              ))}
            </div>
          </article>
        ))}
      </section>
    </section>
  );
}

function Platform({ data, error, now }) {
  const platform = data.platforms.find((item) => item.id === "p1") || data.platforms[0];
  const nextTrain = platform.trains[0];
  const recommendedCoach =
    nextTrain.coaches.find((coach) => coach.coach === nextTrain.recommendedCoach) ||
    nextTrain.coaches.reduce((best, coach) => (coach.load < best.load ? coach : best));
  const upcoming = platform.trains.slice(1, 3);

  return (
    <section className="display platform">
      <Header
        title={`${platform.name} PIDS`}
        subtitle={`${data.line?.name || "MRT Kajang Line"} · ${platform.direction}`}
        data={data}
        error={error}
        now={now}
      />
      <section className="platform-main">
        <article className="panel next-panel">
          <div>
            <div className="label">Next Train</div>
            <div className="destination">{nextTrain.destination}</div>
            <div className="train-no">{nextTrain.id}</div>
            <div className="meta">4-Coach Train · {nextTrain.service} · ETA {formatTime(nextTrain.arrivalTime)}</div>
          </div>
          <div className="arrival-row">
            <div className={`mins ${nextTrain.isArrived ? "now" : ""}`}>{nextTrain.arrivalLabel || nextTrain.arrivalMins}</div>
            <div className={`arrival-text ${nextTrain.isArrived ? "now-label" : ""}`}>
              {nextTrain.isArrived ? <>train<br />arrived</> : <>min<br />arriving</>}
            </div>
          </div>
        </article>
        <aside className="panel right-panel">
          <div className="section-head">
            <div>
              <div className="label">First Train CDA</div>
              <div className="section-title">Coach Load</div>
            </div>
            <div className="status-pill">Best: Coach {recommendedCoach.coach}</div>
          </div>
          <div className="coach-grid">
            {nextTrain.coaches.map((coach) => {
              const klass = cdaClass(coach.load);
              const recommended = coach.coach === recommendedCoach.coach;
              return (
                <div className="coach" key={coach.coach}>
                  <div>
                    <div className="coach-name">Coach {coach.coach}</div>
                    <div className={`pct ${klass}`}>{coach.load}%</div>
                    <div className="bar"><div className={`fill ${klass}`} style={{ width: `${coach.load}%` }} /></div>
                  </div>
                  <div className="coach-desc">{coachDescription(coach.load, recommended)}</div>
                </div>
              );
            })}
          </div>
          <div className="ai-box">
            <div className="ai-title">AI Recommendation</div>
            <div className="ai-text">{nextTrain.platformAdvisory}</div>
          </div>
        </aside>
      </section>
      <section className="upcoming-strip">
        {upcoming.map((train, index) => (
          <div className="upcoming-card" key={train.id}>
            <div>
              <div className="label">Upcoming {index + 1}</div>
              <div className="small-train">{train.id}</div>
              <div className="small-meta">Toward {train.destination} · ETA {formatTime(train.arrivalTime)}</div>
            </div>
            <div>
              <Arrival train={train} sizeClass="small-mins" />
            </div>
          </div>
        ))}
      </section>
    </section>
  );
}

function Classic({ data, now }) {
  const platform = data.platforms.find((item) => item.id === "p1") || data.platforms[0];
  const trains = platform.trains.slice(0, 3);
  const platformTitle = uppercaseWords(platform.name);
  const rowLabels = ["1st", "2nd", "3rd"];

  return (
    <section className="classic-display">
      <article className="classic-board" aria-label={`${platformTitle} display`}>
        <header className="classic-header">
          <img className="classic-logo" src="/assets/mrt-corp-logo.png" alt="MRT Corp" />
          <h1>{platformTitle}</h1>
          <div className="classic-time">
            <strong>{formatTime(now, true)}</strong>
            <span>{formatDate(now)}</span>
          </div>
        </header>
        <table className="classic-table">
          <thead>
            <tr>
              <th>Train</th>
              <th>Destination</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {trains.map((train, index) => (
              <tr key={train.id}>
                <td>{rowLabels[index] || `${index + 1}th`}</td>
                <td>{uppercaseWords(train.destination)}</td>
                <td>{timeLabel(train)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
    </section>
  );
}

function CoachLoad({ data, now }) {
  const platform = data.platforms.find((item) => item.id === "p1") || data.platforms[0];
  const nextTrain = platform.trains[0];
  const coachTone = (load) => {
    if (load >= 70) return "heavy";
    if (load >= 45) return "moderate";
    return "light";
  };

  return (
    <section className="coach-load-display">
      <article className="coach-load-board" aria-label={`${uppercaseWords(platform.name)} coach load display`}>
        <header className="coach-load-header">
          <img className="coach-load-logo" src="/assets/mrt-corp-logo.png" alt="MRT Corp" />
          <h1>{uppercaseWords(platform.name)}</h1>
          <div className="coach-load-time">
            <strong>{formatTime(now, true)}</strong>
            <span>{formatDate(now)}</span>
          </div>
        </header>

        <section className="coach-load-service" aria-label="Next train">
          <div className="coach-load-labels">
            <div>Train</div>
            <div>Destination</div>
            <div>Time</div>
          </div>
          <div className="coach-load-values">
            <div>1st</div>
            <div>{uppercaseWords(nextTrain.destination)}</div>
            <div>{timeLabel(nextTrain)}</div>
          </div>
        </section>

        <section className="coach-load-coaches" aria-label="Coach load">
          {nextTrain.coaches.map((coach) => (
            <div className="coach-load-car" key={coach.coach}>
              <div className={`coach-load-bar ${coachTone(coach.load)}`} />
              <div>COACH {coach.coach}</div>
            </div>
          ))}
        </section>

        <footer className="coach-load-alert">
          NEXT TRAIN {uppercaseWords(nextTrain.crowdCondition || cdaLabel(nextTrain.crowdDensity))} CROWDED
        </footer>
      </article>
    </section>
  );
}

function ErrorScreen({ error }) {
  return (
    <section className="display error-display">
      <article className="panel error-panel">
        <div className="label">AI PIDS unavailable</div>
        <h1>OpenAI key required</h1>
        <p>{error || "Set OPENAI_API_KEY in .env and restart the backend."}</p>
      </article>
    </section>
  );
}

function App() {
  const [mode, setMode] = useState(currentMode);
  const now = useClock();
  const { data, error } = useDisplayData();

  useEffect(() => {
    const updateMode = () => setMode(currentMode());
    window.addEventListener("popstate", updateMode);
    window.addEventListener("hashchange", updateMode);
    return () => {
      window.removeEventListener("popstate", updateMode);
      window.removeEventListener("hashchange", updateMode);
    };
  }, []);

  useEffect(() => {
    if ("serviceWorker" in navigator && import.meta.env.PROD) {
      navigator.serviceWorker.register("/service-worker.js");
    }
  }, []);

  const content = useMemo(() => {
    if (!data) return <ErrorScreen error={error || "Loading live AI display data..."} />;
    if (mode === "coach-load") return <CoachLoad data={data} now={now} />;
    if (mode === "platform") return <Platform data={data} error={error} now={now} />;
    if (mode === "concourse") return <Concourse data={data} error={error} now={now} />;
    return <Classic data={data} now={now} />;
  }, [data, error, mode, now]);

  return content;
}

createRoot(document.getElementById("root")).render(<App />);
