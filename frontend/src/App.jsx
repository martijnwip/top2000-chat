import { useEffect, useRef, useState } from "react";
import "./App.css";

const PAD_LABEL = {
  sql: "sql",
  rag_songs: "rag · songs",
  rag_project: "rag · project",
};

// Voorbeeldgesprek voor ./start.sh --demo — zie App() en de useEffect met
// de "demo"-URL-parameter.
const DEMO_VRAGEN = [
  "Wie stond er op positie 2000 van het jaar 1999?",
  "Wat was de hoogste notering van James Brown",
  "Hoe vaak staat Aretha Franklin in de lijst?",
];

function Tabel({ rijen }) {
  if (!rijen || rijen.length === 0) return null;
  const kolommen = Object.keys(rijen[0]);
  return (
    <table className="tabel">
      <thead>
        <tr>
          {kolommen.map((k) => (
            <th key={k}>{k}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rijen.map((rij, i) => (
          <tr key={i}>
            {kolommen.map((k) => (
              <td key={k}>
                {k === "cosine" && typeof rij[k] === "number"
                  ? rij[k].toFixed(3)
                  : String(rij[k] ?? "")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Gemiddeld stroomverbruik van een wasbeurt op 40°C: 0,5 kWh (Milieu Centraal).
const WASBEURT_WH = 500;

function WasmachineIcoon({ grootte = 18 }) {
  return (
    <svg
      width={grootte}
      height={grootte}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="7.5" cy="6.5" r="0.6" fill="currentColor" stroke="none" />
      <circle cx="10.5" cy="6.5" r="0.6" fill="currentColor" stroke="none" />
      <circle cx="12" cy="14" r="5" />
      <path d="M9.5 12.5a3 3 0 0 0 5 3" />
    </svg>
  );
}

function VerbruikTotaal({ berichten }) {
  const metingen = berichten
    .filter((b) => b.rol === "assistent" && b.resultaat?.verbruik_bron)
    .map((b) => b.resultaat);

  if (metingen.length === 0) return null;

  const wh = metingen.reduce((som, r) => som + r.energie_wh, 0);
  const co2 = metingen.reduce((som, r) => som + r.co2_g, 0);
  const laatste = metingen[metingen.length - 1];
  const fractieWasbeurt = wh / WASBEURT_WH;
  const percentage = Math.min(100, fractieWasbeurt * 100);

  return (
    <details className="verbruik-knop">
      <summary>
        <WasmachineIcoon />
        <span>
          {(fractieWasbeurt * 100).toFixed(3)}% van een wasbeurt &middot;{" "}
          {wh.toFixed(3)} Wh
        </span>
      </summary>
      <div className="verbruik-detail">
        <div className="wasbalk-rij">
          <div
            className="wasbalk"
            role="progressbar"
            aria-valuenow={Math.round(percentage)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="wasbalk-vulling"
              style={{ width: `${percentage}%` }}
            />
          </div>
          <WasmachineIcoon grootte={30} />
        </div>
        <p className="wasbalk-tekst">
          {(fractieWasbeurt * 100).toFixed(3)}% van een wasbeurt op 40&deg;C
          (0,5 kWh per wasbeurt, bron: Milieu Centraal)
        </p>
        <p className="verbruik-cijfers">
          {wh.toFixed(3)} Wh &middot; {co2.toFixed(3)} g CO&#8322; &middot;{" "}
          {metingen.length} antwoord{metingen.length === 1 ? "" : "en"}
          <span className="verbruik-bron"> ({laatste.verbruik_bron})</span>
        </p>
        {laatste.verbruik_dekking && (
          <p className="verbruik-dekking">{laatste.verbruik_dekking}</p>
        )}
      </div>
    </details>
  );
}

function Onderbouwing({ resultaat }) {
  const isRag = resultaat.pad !== "sql";
  const rijen = isRag ? resultaat.bronnen : resultaat.rijen;

  return (
    <details className="onderbouwing">
      <summary>
        pad: {PAD_LABEL[resultaat.pad] ?? resultaat.pad} (regel:{" "}
        {resultaat.regel}
        {resultaat.signaal ? ` op "${resultaat.signaal}"` : ""})
      </summary>
      {resultaat.sql && (
        <pre className="sql">
          <code>{resultaat.sql}</code>
        </pre>
      )}
      <Tabel rijen={rijen} />
      <p className="looptijd">
        {resultaat.looptijd_s.toFixed(1)}s
        {isRag && resultaat.cosine != null
          ? ` · beste cosine ${resultaat.cosine.toFixed(3)}`
          : ""}
        {!isRag ? ` · ${resultaat.pogingen} poging(en)` : ""}
      </p>
      {resultaat.verbruik_dekking && (
        <p className="verbruik-dekking">{resultaat.verbruik_dekking}</p>
      )}
    </details>
  );
}

function Nadenken() {
  const [aantalStippen, setAantalStippen] = useState(1);

  useEffect(() => {
    const interval = setInterval(() => {
      setAantalStippen((n) => (n % 3) + 1);
    }, 450);
    return () => clearInterval(interval);
  }, []);

  return (
    <p className="denkt">
      bezig met nadenken
      <span className="stippen">{".".repeat(aantalStippen)}</span>
    </p>
  );
}

function Bericht({ bericht }) {
  if (bericht.rol === "gebruiker") {
    return (
      <div className="bericht bericht-gebruiker">
        <p>{bericht.tekst}</p>
      </div>
    );
  }

  return (
    <div className="bericht bericht-assistent">
      {bericht.bezig && <Nadenken />}
      {bericht.fout && <p className="fout">{bericht.fout}</p>}
      {bericht.resultaat && (
        <>
          <p className="antwoordtekst">{bericht.resultaat.antwoord}</p>
          <Onderbouwing resultaat={bericht.resultaat} />
        </>
      )}
    </div>
  );
}

export default function App() {
  const [vraag, setVraag] = useState("");
  const [berichten, setBerichten] = useState([]);
  const [bezig, setBezig] = useState(false);
  const textareaRef = useRef(null);
  const eindeRef = useRef(null);
  const demoGestart = useRef(false);

  useEffect(() => {
    eindeRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [berichten]);

  function groeiTextarea() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }

  async function stelVraag(tekst) {
    const id = crypto.randomUUID();
    setBerichten((b) => [
      ...b,
      { id: `${id}-vraag`, rol: "gebruiker", tekst },
      { id, rol: "assistent", bezig: true },
    ]);
    setBezig(true);

    try {
      const respons = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vraag: tekst }),
      });
      if (!respons.ok) {
        const body = await respons.json().catch(() => ({}));
        throw new Error(
          body.detail || `${respons.status} ${respons.statusText}`,
        );
      }
      const resultaat = await respons.json();
      setBerichten((b) =>
        b.map((m) => (m.id === id ? { ...m, bezig: false, resultaat } : m)),
      );
    } catch (err) {
      setBerichten((b) =>
        b.map((m) =>
          m.id === id ? { ...m, bezig: false, fout: err.message } : m,
        ),
      );
    } finally {
      setBezig(false);
    }
  }

  async function verstuur(e) {
    e.preventDefault();
    const tekst = vraag.trim();
    if (!tekst || bezig) return;

    setVraag("");
    requestAnimationFrame(groeiTextarea);
    await stelVraag(tekst);
  }

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("demo") !== "1") return;
    // Ref in plaats van een losse vlag: overleeft de dubbele effect-aanroep
    // die React StrictMode in dev doet, zodat het voorbeeldgesprek niet
    // dubbel wordt afgevuurd.
    if (demoGestart.current) return;
    demoGestart.current = true;
    (async () => {
      for (const tekst of DEMO_VRAGEN) {
        await stelVraag(tekst);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toetsAf(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      verstuur(e);
    }
  }

  return (
    <main id="root">
      <header className="chatkop">
        <h1>Top 2000 Chat</h1>
        <p className="ondertitel">
          Vragen over de NPO Radio 2 Top 2000, 1999&ndash;2025. Draait volledig
          lokaal.
        </p>
      </header>

      <div className="gesprek">
        {berichten.length === 0 && (
          <p className="leeg">
            Stel een vraag, bijvoorbeeld &ldquo;Wat stond er op 1 in
            2025?&rdquo;
          </p>
        )}
        {berichten.map((b) => (
          <Bericht key={b.id} bericht={b} />
        ))}
        <div ref={eindeRef} />
      </div>

      <div className="invoergebied">
        <form onSubmit={verstuur} className="vraagform">
          <textarea
            ref={textareaRef}
            value={vraag}
            onChange={(e) => {
              setVraag(e.target.value);
              groeiTextarea();
            }}
            onKeyDown={toetsAf}
            placeholder="Stel een vraag over de Top 2000…"
            disabled={bezig}
            rows={1}
            autoFocus
          />
          <button
            type="submit"
            disabled={bezig || !vraag.trim()}
            aria-label="Verstuur"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 19V5" />
              <path d="M5 12l7-7 7 7" />
            </svg>
          </button>
        </form>
        <VerbruikTotaal berichten={berichten} />
      </div>
    </main>
  );
}
