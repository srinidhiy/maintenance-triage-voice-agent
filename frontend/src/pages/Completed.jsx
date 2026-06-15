import { useState, useEffect, useCallback } from 'react'

const URGENCY_LABEL = { emergency: 'Emergency', urgent: 'Urgent', routine: 'Routine' }

function Badge({ urgency }) {
  const colors = {
    emergency: 'bg-red-100 text-red-800',
    urgent: 'bg-yellow-100 text-yellow-800',
    routine: 'bg-green-100 text-green-800',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[urgency]}`}>
      {URGENCY_LABEL[urgency]}
    </span>
  )
}

export default function Completed() {
  const [tickets, setTickets] = useState([])
  const [filter, setFilter] = useState('')
  const [error, setError] = useState(null)

  const fetchTickets = useCallback(async () => {
    try {
      const res = await fetch('http://localhost:8000/tickets?status=completed')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setTickets(await res.json())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    fetchTickets()
    const id = setInterval(fetchTickets, 15000)
    return () => clearInterval(id)
  }, [fetchTickets])

  const visible = tickets.filter(t =>
    !filter || t.summary.toLowerCase().includes(filter.toLowerCase())
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-gray-800">Completed Requests</h1>
        <input
          type="text"
          placeholder="Filter by summary..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      </div>
      {error && <p className="text-sm text-red-600 mb-3">Could not load tickets: {error}</p>}
      {visible.length === 0 && !error && (
        <p className="text-sm text-gray-500">No completed requests.</p>
      )}
      {visible.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-left">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
              <tr>
                <th className="py-2 px-4">ID</th>
                <th className="py-2 px-4">Summary</th>
                <th className="py-2 px-4">Urgency</th>
                <th className="py-2 px-4">Duration</th>
                <th className="py-2 px-4">Tenant</th>
              </tr>
            </thead>
            <tbody>
              {visible.map(t => (
                <tr key={t.id} className="border-t border-gray-100">
                  <td className="py-3 px-4 font-mono text-xs text-gray-400">{t.id.slice(0, 8)}</td>
                  <td className="py-3 px-4 text-sm">{t.summary}</td>
                  <td className="py-3 px-4"><Badge urgency={t.urgency} /></td>
                  <td className="py-3 px-4 text-sm text-gray-600">{t.estimated_duration_minutes} min</td>
                  <td className="py-3 px-4 text-sm text-gray-500">{t.tenant_id ?? 'Unmatched'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
