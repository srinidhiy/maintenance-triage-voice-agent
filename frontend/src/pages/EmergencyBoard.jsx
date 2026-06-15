import { useState, useEffect, useCallback } from 'react'

const URGENCY_LABEL = { emergency: 'Emergency', urgent: 'Urgent', routine: 'Routine' }
const STATUS_TRANSITIONS = {
  open: ['in_progress'],
  in_progress: ['completed'],
  completed: [],
}

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

function StatusBadge({ status }) {
  const colors = {
    open: 'bg-gray-100 text-gray-700',
    in_progress: 'bg-blue-100 text-blue-800',
    completed: 'bg-green-100 text-green-800',
    incomplete: 'bg-orange-100 text-orange-700',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] ?? 'bg-gray-100 text-gray-700'}`}>
      {status.replace('_', ' ')}
    </span>
  )
}

function TicketRow({ ticket, onAdvance }) {
  const next = STATUS_TRANSITIONS[ticket.status]?.[0]
  return (
    <tr className="border-t border-gray-100">
      <td className="py-3 px-4 font-mono text-xs text-gray-400">{ticket.id.slice(0, 8)}</td>
      <td className="py-3 px-4 text-sm">{ticket.summary}</td>
      <td className="py-3 px-4"><Badge urgency={ticket.urgency} /></td>
      <td className="py-3 px-4"><StatusBadge status={ticket.status} /></td>
      <td className="py-3 px-4 text-xs text-gray-500">{ticket.tenant_id ?? 'Unmatched'}</td>
      <td className="py-3 px-4">
        {next && (
          <button
            onClick={() => onAdvance(ticket.id, next)}
            className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700"
          >
            Mark {next.replace('_', ' ')}
          </button>
        )}
      </td>
    </tr>
  )
}

export default function EmergencyBoard() {
  const [tickets, setTickets] = useState([])
  const [error, setError] = useState(null)

  const fetchTickets = useCallback(async () => {
    try {
      const res = await fetch('http://localhost:8000/tickets/emergency')
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

  async function handleAdvance(ticketId, newStatus) {
    await fetch(`http://localhost:8000/tickets/${ticketId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    })
    fetchTickets()
  }

  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-800 mb-4">Emergency Board</h1>
      {error && <p className="text-sm text-red-600 mb-3">Could not load tickets: {error}</p>}
      {tickets.length === 0 && !error && (
        <p className="text-sm text-gray-500">No active emergencies.</p>
      )}
      {tickets.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-left">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
              <tr>
                <th className="py-2 px-4">ID</th>
                <th className="py-2 px-4">Summary</th>
                <th className="py-2 px-4">Urgency</th>
                <th className="py-2 px-4">Status</th>
                <th className="py-2 px-4">Tenant</th>
                <th className="py-2 px-4">Action</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map(t => (
                <TicketRow key={t.id} ticket={t} onAdvance={handleAdvance} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
