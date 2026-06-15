import { useState, useEffect, useCallback } from 'react'
import { Calendar, dateFnsLocalizer } from 'react-big-calendar'
import { format, parse, startOfWeek, getDay } from 'date-fns'
import { enUS } from 'date-fns/locale'

const localizer = dateFnsLocalizer({
  format,
  parse,
  startOfWeek: () => startOfWeek(new Date(), { weekStartsOn: 1 }),
  getDay,
  locales: { 'en-US': enUS },
})

const EVENT_COLORS = {
  emergency: '#ef4444',
  urgent: '#f59e0b',
  routine: '#22c55e',
  travel: '#94a3b8',
}

const URGENCY_LABEL = { emergency: 'Emergency', urgent: 'Urgent', routine: 'Routine' }

function eventStyleGetter(event) {
  return {
    style: {
      backgroundColor: EVENT_COLORS[event.type] ?? '#6b7280',
      borderRadius: '4px',
      border: 'none',
      color: event.type === 'travel' ? '#1e293b' : '#fff',
      fontSize: '12px',
    },
  }
}

function toCalendarEvent(item) {
  if (item.type === 'travel') {
    return {
      id: `travel-${item.from_building_id}-${item.to_building_id}-${item.start}`,
      title: `Travel (${item.duration_minutes} min)`,
      start: new Date(item.start),
      end: new Date(item.end),
      type: 'travel',
      meta: item,
    }
  }
  const t = item.ticket
  return {
    id: t.id,
    title: t.summary,
    start: new Date(t.scheduled_start),
    end: new Date(new Date(t.scheduled_start).getTime() + t.estimated_duration_minutes * 60000),
    type: t.urgency,
    atRisk: t.at_risk,
    meta: item,
  }
}

function Row({ label, value }) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="text-gray-500 w-32 shrink-0">{label}</span>
      <span className="text-gray-900">{value}</span>
    </div>
  )
}

function EventModal({ event, onClose }) {
  if (!event) return null
  const isTravel = event.type === 'travel'
  const { meta } = event

  return (
    <div
      className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 relative"
        onClick={e => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-lg leading-none"
        >
          ✕
        </button>

        {isTravel ? (
          <>
            <h2 className="font-semibold text-gray-800 mb-4">Travel Block</h2>
            <div className="space-y-2">
              <Row label="From" value={meta.from_name ?? meta.from_building} />
              <Row label="To" value={meta.to_name ?? meta.to_building} />
              <Row label="Duration" value={`${meta.duration_minutes} min`} />
              <Row label="Start" value={event.start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} />
              <Row label="End" value={event.end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} />
            </div>
          </>
        ) : (
          <>
            <div className="mb-4 pr-6">
              <span
                className="inline-block mb-2 px-2 py-0.5 rounded text-xs font-medium"
                style={{
                  backgroundColor: EVENT_COLORS[event.type] + '22',
                  color: EVENT_COLORS[event.type],
                }}
              >
                {URGENCY_LABEL[event.type]}
              </span>
              <h2 className="font-semibold text-gray-800 leading-snug">{event.title}</h2>
            </div>
            <div className="space-y-2">
              <Row label="Status" value={meta.ticket.status.replace('_', ' ')} />
              <Row label="Building" value={meta.building_name ?? '—'} />
              <Row label="Tenant" value={meta.tenant_name ?? 'Unmatched'} />
              <Row
                label="Scheduled start"
                value={event.start.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
              />
              <Row label="Duration" value={`${meta.ticket.estimated_duration_minutes} min`} />
              <Row label="Confidence" value={`${Math.round(meta.ticket.confidence * 100)}%`} />
              {meta.ticket.at_risk && (
                <p className="text-xs text-amber-700 bg-amber-50 rounded px-3 py-2 mt-2">
                  ⚠ At risk of exceeding end of business
                </p>
              )}
              {meta.ticket.instructions && (
                <div className="mt-3 pt-3 border-t border-gray-100">
                  <p className="text-xs text-gray-500 mb-1">Instructions</p>
                  <p className="text-sm text-gray-700">{meta.ticket.instructions}</p>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default function Schedule() {
  const [paused, setPaused] = useState(false)
  const [events, setEvents] = useState([])
  const [error, setError] = useState(null)
  const [date, setDate] = useState(new Date())
  const [selected, setSelected] = useState(null)

  const fetchSchedule = useCallback(async () => {
    try {
      const res = await fetch('http://localhost:8000/schedule')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setPaused(data.paused)
      setEvents((data.items ?? []).map(toCalendarEvent))
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    fetchSchedule()
    const id = setInterval(fetchSchedule, 15000)
    return () => clearInterval(id)
  }, [fetchSchedule])

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <h1 className="text-xl font-semibold text-gray-800">Schedule</h1>
        {paused && (
          <span className="bg-red-100 text-red-800 text-xs font-medium px-3 py-1 rounded-full">
            Paused — active emergency
          </span>
        )}
      </div>
      {error && <p className="text-sm text-red-600 mb-3">Could not load schedule: {error}</p>}
      <div className="bg-white rounded-lg shadow p-4" style={{ height: 620 }}>
        <Calendar
          localizer={localizer}
          events={events}
          defaultView="week"
          date={date}
          onNavigate={setDate}
          eventPropGetter={eventStyleGetter}
          tooltipAccessor={null}
          onSelectEvent={setSelected}
          style={{ height: '100%' }}
        />
      </div>
      <div className="flex gap-4 mt-3 text-xs text-gray-600">
        {[['emergency', 'Emergency'], ['urgent', 'Urgent'], ['routine', 'Routine'], ['travel', 'Travel']].map(([key, label]) => (
          <span key={key} className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: EVENT_COLORS[key] }} />
            {label}
          </span>
        ))}
      </div>

      <EventModal event={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
