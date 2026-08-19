import { useEffect, useRef, useState } from 'react'
import './App.css'

const PAD_LABEL = {
  sql: 'sql',
  rag_songs: 'rag · songs',
  rag_project: 'rag · project',
}

function Tabel({ rijen }) {
  if (!rijen || rijen.length === 0) return null
  const kolommen = Object.keys(rijen[0])
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
                {k === 'cosine' && typeof rij[k] === 'number'
                  ? rij[k].toFixed(3)
                  : String(rij[k] ?? '')}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Verbruik({ resultaat }) {
  if (!resultaat.verbruik_bron) return null
  return (
    <p className="verbruik" title={resultaat.verbruik_dekking}>
      {resultaat.energie_wh.toFixed(3)} Wh &middot; {resultaat.co2_g.toFixed(3)} g CO&#8322;
      <span className="verbruik-bron"> ({resultaat.verbruik_bron})</span>
    </p>
  )
}

function Onderbouwing({ resultaat }) {
  const isRag = resultaat.pad !== 'sql'
  const rijen = isRag ? resultaat.bronnen : resultaat.rijen

  return (
    <details className="onderbouwing">
      <summary>
        pad: {PAD_LABEL[resultaat.pad] ?? resultaat.pad} (regel:{' '}
        {resultaat.regel}
        {resultaat.signaal ? ` op "${resultaat.signaal}"` : ''})
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
          : ''}
        {!isRag ? ` · ${resultaat.pogingen} poging(en)` : ''}
      </p>
      {resultaat.verbruik_dekking && (
        <p className="verbruik-dekking">{resultaat.verbruik_dekking}</p>
      )}
    </details>
  )
}

function Bericht({ bericht }) {
  if (bericht.rol === 'gebruiker') {
    return (
      <div className="bericht bericht-gebruiker">
        <p>{bericht.tekst}</p>
      </div>
    )
  }

  return (
    <div className="bericht bericht-assistent">
      {bericht.bezig && <p className="denkt">bezig met nadenken&hellip;</p>}
      {bericht.fout && <p className="fout">{bericht.fout}</p>}
      {bericht.resultaat && (
        <>
          <p className="antwoordtekst">{bericht.resultaat.antwoord}</p>
          <Verbruik resultaat={bericht.resultaat} />
          <Onderbouwing resultaat={bericht.resultaat} />
        </>
      )}
    </div>
  )
}

export default function App() {
  const [vraag, setVraag] = useState('')
  const [berichten, setBerichten] = useState([])
  const [bezig, setBezig] = useState(false)
  const textareaRef = useRef(null)
  const eindeRef = useRef(null)

  useEffect(() => {
    eindeRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [berichten])

  function groeiTextarea() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`
  }

  async function verstuur(e) {
    e.preventDefault()
    const tekst = vraag.trim()
    if (!tekst || bezig) return

    const id = crypto.randomUUID()
    setBerichten((b) => [
      ...b,
      { id: `${id}-vraag`, rol: 'gebruiker', tekst },
      { id, rol: 'assistent', bezig: true },
    ])
    setVraag('')
    setBezig(true)
    requestAnimationFrame(groeiTextarea)

    try {
      const respons = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vraag: tekst }),
      })
      if (!respons.ok) {
        const body = await respons.json().catch(() => ({}))
        throw new Error(body.detail || `${respons.status} ${respons.statusText}`)
      }
      const resultaat = await respons.json()
      setBerichten((b) =>
        b.map((m) => (m.id === id ? { ...m, bezig: false, resultaat } : m)),
      )
    } catch (err) {
      setBerichten((b) =>
        b.map((m) => (m.id === id ? { ...m, bezig: false, fout: err.message } : m)),
      )
    } finally {
      setBezig(false)
    }
  }

  function toetsAf(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      verstuur(e)
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
              setVraag(e.target.value)
              groeiTextarea()
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
      </div>
    </main>
  )
}
