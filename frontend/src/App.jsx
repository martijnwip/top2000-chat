import { useState } from 'react'
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

export default function App() {
  const [vraag, setVraag] = useState('')
  const [bezig, setBezig] = useState(false)
  const [resultaat, setResultaat] = useState(null)
  const [fout, setFout] = useState(null)

  async function verstuur(e) {
    e.preventDefault()
    const tekst = vraag.trim()
    if (!tekst || bezig) return

    setBezig(true)
    setFout(null)
    setResultaat(null)
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
      setResultaat(await respons.json())
    } catch (err) {
      setFout(err.message)
    } finally {
      setBezig(false)
    }
  }

  return (
    <main id="root">
      <h1>Top 2000 Chat</h1>
      <p className="ondertitel">
        Vragen over de NPO Radio 2 Top 2000, 1999&ndash;2025. Draait volledig
        lokaal.
      </p>

      <form onSubmit={verstuur} className="vraagform">
        <input
          type="text"
          value={vraag}
          onChange={(e) => setVraag(e.target.value)}
          placeholder="Wat stond er op 1 in 2025?"
          disabled={bezig}
          autoFocus
        />
        <button type="submit" disabled={bezig || !vraag.trim()}>
          {bezig ? 'Bezig…' : 'Vraag'}
        </button>
      </form>

      {fout && <p className="fout">{fout}</p>}

      {resultaat && (
        <section className="antwoord">
          <p className="antwoordtekst">{resultaat.antwoord}</p>
          <Verbruik resultaat={resultaat} />
          <Onderbouwing resultaat={resultaat} />
        </section>
      )}
    </main>
  )
}
