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
  }
}

export default function Schedule() {
  const [paused, setPaused] = useState(false)
  const [events, setEvents] = useState([])
  const [error, setError] = useState(null)
  const [date, setDate] = useState(new Date())

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
          tooltipAccessor={e => e.atRisk ? `${e.title} ⚠ at risk` : e.title}
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
    </div>
  )
}
