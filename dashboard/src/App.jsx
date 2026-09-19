import { useEffect, useState } from 'react'
import './App.css'

const initialState = { services: [], events: [], error: '' }

function statusLabel(status) {
  return status === 'healthy' ? 'Healthy' : 'Unhealthy'
}

function App() {
  const [state, setState] = useState(initialState)

  useEffect(() => {
    let active = true

    async function loadDashboard() {
      try {
        const [servicesResponse, eventsResponse] = await Promise.all([
          fetch('/api/services'),
          fetch('/api/events?limit=100'),
        ])
        if (!servicesResponse.ok || !eventsResponse.ok) {
          throw new Error('Relay API is unavailable')
        }
        const services = await servicesResponse.json()
        const events = await eventsResponse.json()
        if (active) {
          setState({ services: services.services, events: events.events, error: '' })
        }
      } catch (error) {
        if (active) {
          setState((current) => ({ ...current, error: error.message }))
        }
      }
    }

    loadDashboard()
    const refresh = window.setInterval(loadDashboard, 10000)
    const stream = new EventSource('/api/events/stream')

    stream.onmessage = (message) => {
      const event = JSON.parse(message.data)
      setState((current) => ({
        ...current,
        events: [event, ...current.events].slice(0, 100),
        services: current.services.map((service) =>
          service.name === event.service && event.type === 'service_recovered'
            ? { ...service, status: 'healthy' }
            : service.name === event.service && event.type === 'health_failure'
              ? { ...service, status: 'unhealthy' }
              : service,
        ),
        error: '',
      }))
    }

    stream.onerror = () => {
      if (active) {
        setState((current) => ({ ...current, error: 'Live event stream disconnected' }))
      }
    }

    return () => {
      active = false
      window.clearInterval(refresh)
      stream.close()
    }
  }, [])

  return (
    <main className="dashboard-shell">
      <header className="dashboard-header">
        <div>
          <p className="eyebrow">AUTODECK / CONTROL PLANE</p>
          <h1>Service recovery dashboard</h1>
          <p className="subtitle">Live health and self-healing activity from the registered topology.</p>
        </div>
        <div className={`connection ${state.error ? 'offline' : 'online'}`}>
          <span /> {state.error ? 'Relay disconnected' : 'Relay connected'}
        </div>
      </header>

      {state.error && <div className="alert">{state.error}</div>}

      <section className="section-block">
        <div className="section-heading">
          <div>
            <p className="eyebrow">SERVICE REGISTRY</p>
            <h2>Registered services</h2>
          </div>
          <span className="count">{state.services.length} services</span>
        </div>
        <div className="service-grid">
          {state.services.map((service) => (
            <article className="service-card" key={service.name}>
              <div className="card-topline">
                <div>
                  <p className="service-name">{service.name}</p>
                  <p className="service-entry">127.0.0.1:{service.port}</p>
                </div>
                <span className={`status-pill ${service.status}`}>
                  <span /> {statusLabel(service.status)}
                </span>
              </div>
              <dl>
                <div><dt>Health</dt><dd>{service.health}</dd></div>
                <div><dt>Depends on</dt><dd>{service.depends_on?.join(', ') || 'none'}</dd></div>
                <div><dt>Endpoints</dt><dd>{service.endpoints?.join(', ') || 'none'}</dd></div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block events-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">EVENT STREAM</p>
            <h2>Recovery timeline</h2>
          </div>
          <span className="count">Latest {state.events.length}</span>
        </div>
        <div className="event-list">
          {state.events.length === 0 ? (
            <p className="empty-state">No recovery events yet.</p>
          ) : state.events.map((event) => (
            <article className="event-row" key={event.id}>
              <span className={`event-marker ${event.status}`} />
              <div className="event-main">
                <div className="event-title">
                  <strong>{event.service}</strong>
                  <span>{event.type.replaceAll('_', ' ')}</span>
                </div>
                <p>{event.message}</p>
              </div>
              <time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString()}</time>
            </article>
          ))}
        </div>
      </section>
    </main>
  )
}

export default App
