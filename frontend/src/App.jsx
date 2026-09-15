import { useState } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const SAMPLE = `Hi,

Please quote the following for the pump skid rebuild:
- 10 x Ball Valve 1/2" SS316 Threaded
- 4 x Gate Valve 3" CS Flanged Class 150
- 50 x 90 Deg Elbow 1/2" SS304 Socket Weld
- qty 25 hex head bolt M12x50 SS316 DIN 933

Need it on site by the 30th.

Thanks,
Paul
Acme Industrial`;

const money = (n) =>
  n == null ? "" : n.toLocaleString("en-US", { style: "currency", currency: "USD" });

function Availability({ line }) {
  const map = {
    in_stock: ["In stock", "ok"],
    partial: [`${line.stock_qty} on hand`, "warn"],
    backorder: [`Backorder ${line.lead_time_days}d`, "bad"],
    unknown: ["—", "muted"],
  };
  const [label, cls] = map[line.availability] || map.unknown;
  return <span className={`pill ${cls}`}>{label}</span>;
}

function LineRow({ line, onChange }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <tr className={line.needs_review ? "review" : ""}>
        <td className="num">{line.line_no}</td>
        <td>
          <div className="desc">{line.product_name || line.description}</div>
          <div className="raw" title={line.raw_text}>{line.raw_text}</div>
        </td>
        <td>
          {line.candidates.length > 0 ? (
            <select
              value={line.sku || ""}
              onChange={(e) => onChange(line.line_no, e.target.value)}
            >
              <option value="">— not matched —</option>
              {line.candidates.map((c) => (
                <option key={c.sku} value={c.sku}>
                  {c.sku} · {(c.score * 100).toFixed(0)}%
                </option>
              ))}
            </select>
          ) : (
            <span className="muted">no candidate</span>
          )}
        </td>
        <td className="num">{line.quantity}</td>
        <td className="num">{money(line.unit_price)}</td>
        <td className="num strong">{money(line.line_total)}</td>
        <td><Availability line={line} /></td>
        <td>
          <button className="link" onClick={() => setOpen(!open)}>
            {(line.confidence * 100).toFixed(0)}% {open ? "▴" : "▾"}
          </button>
        </td>
      </tr>

      {open && (
        <tr className="detail">
          <td />
          <td colSpan={7}>
            {line.review_reason && (
              <p className="flag">Flagged: {line.review_reason}</p>
            )}
            <table className="inner">
              <tbody>
                {line.candidates.map((c) => (
                  <tr key={c.sku}>
                    <td className="mono">{c.sku}</td>
                    <td>{c.name}</td>
                    <td className="num">{(c.score * 100).toFixed(0)}%</td>
                    <td className="muted">{c.reasons.join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </>
  );
}

export default function App() {
  const [text, setText] = useState(SAMPLE);
  const [tier, setTier] = useState("standard");
  const [useLlm, setUseLlm] = useState(true);
  const [quote, setQuote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [edits, setEdits] = useState({});
  const [saved, setSaved] = useState(null);

  async function generate() {
    setBusy(true);
    setError(null);
    setSaved(null);
    setEdits({});
    try {
      const res = await fetch(`${API}/quote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, customer_tier: tier, use_llm: useLlm }),
      });
      if (!res.ok) throw new Error(await res.text());
      setQuote(await res.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function changeSku(lineNo, sku) {
    setQuote((q) => {
      const lines = q.lines.map((l) => {
        if (l.line_no !== lineNo) return l;
        const c = l.candidates.find((x) => x.sku === sku);
        setEdits((e) => ({ ...e, [lineNo]: { was: l.sku, now: sku } }));
        return { ...l, sku, product_name: c ? c.name : l.product_name, needs_review: false };
      });
      return { ...q, lines };
    });
  }

  async function saveCorrections() {
    const corrections = Object.entries(edits).map(([lineNo, e]) => {
      const line = quote.lines.find((l) => l.line_no === Number(lineNo));
      return {
        raw_text: line.raw_text,
        description: line.description,
        wrong_sku: e.was,
        correct_sku: e.now,
      };
    });
    const res = await fetch(`${API}/quote/${quote.quote_id}/corrections`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quote_id: quote.quote_id, corrections }),
    });
    const data = await res.json();
    setSaved(`${data.learned} correction(s) saved. Next quote will use them.`);
    setEdits({});
  }

  const reviewCount = quote ? quote.lines.filter((l) => l.needs_review).length : 0;

  return (
    <div className="page">
      <header>
        <h1>RFQ Copilot</h1>
        <p>Paste a request-for-quote email. Get a draft quote you can review line by line.</p>
      </header>

      <section className="input">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={14} />
        <div className="controls">
          <label>
            Customer tier
            <select value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value="standard">Standard</option>
              <option value="silver">Silver (5%)</option>
              <option value="gold">Gold (10%)</option>
            </select>
          </label>
          <label className="check">
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
            Use LLM extractor
          </label>
          <button className="primary" onClick={generate} disabled={busy}>
            {busy ? "Working…" : "Generate quote"}
          </button>
        </div>
      </section>

      {error && <p className="error">{error}</p>}

      {quote && (
        <section className="result">
          <div className="summary">
            <div><span>Quote</span><strong className="mono">{quote.quote_id}</strong></div>
            <div><span>Lines</span><strong>{quote.lines.length}</strong></div>
            <div><span>Need review</span><strong className={reviewCount ? "warnText" : ""}>{reviewCount}</strong></div>
            <div><span>Extractor</span><strong>{quote.extractor}</strong></div>
            <div><span>Subtotal</span><strong>{money(quote.subtotal)}</strong></div>
          </div>

          {quote.warnings.length > 0 && (
            <ul className="warnings">
              {quote.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}

          <table className="lines">
            <thead>
              <tr>
                <th>#</th><th>Item</th><th>SKU</th><th>Qty</th>
                <th>Unit</th><th>Total</th><th>Availability</th><th>Conf.</th>
              </tr>
            </thead>
            <tbody>
              {quote.lines.map((l) => (
                <LineRow key={l.line_no} line={l} onChange={changeSku} />
              ))}
            </tbody>
          </table>

          <div className="actions">
            {Object.keys(edits).length > 0 && (
              <button onClick={saveCorrections}>
                Save {Object.keys(edits).length} correction(s)
              </button>
            )}
            <a className="button" href={`${API}/quote/${quote.quote_id}/export`}>
              Export CSV
            </a>
            {saved && <span className="ok">{saved}</span>}
          </div>
        </section>
      )}
    </div>
  );
}
