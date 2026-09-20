import { useEffect, useMemo, useState } from 'react'
import dagre from '@dagrejs/dagre'
import { Background, Controls, Handle, MarkerType, Position, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import './App.css'

const initialState = { services: [], events: [], topology: { nodes: [], edges: [] }, error: '', setup: '' }

function statusLabel(status) {
  if (status === 'healthy') return 'Healthy'
  if (status === 'unknown') return 'Unknown'
  return 'Unhealthy'
}

const IMPORTANT_EVENT_TYPES = new Set([
  'application_failure',
  'application_recovered',
  'agent_diagnosis',
  'health_failure',
  'restart_requested',
  'service_started',
  'service_recovered',
  'recovery_failed',
  'patch_applied',
  'patch_rejected',
  'repair_pending',
  'replay_failed',
])

const FAILURE_EVENT_TYPES = new Set([
  'application_failure',
  'health_failure',
  'recovery_failed',
  'replay_failed',
  'patch_rejected',
  'telemetry_request_failed',
])

const CLEAR_EVENT_TYPES = new Set(['application_recovered', 'service_recovered'])

function eventLabel(type) {
  return type.replaceAll('_', ' ')
}

function incidentState(events) {
  const incidents = {}
  for (const event of [...events].reverse()) {
    const metadata = event.metadata || {}
    const affectedServices = Array.isArray(metadata.affected_services) ? metadata.affected_services : []
    const services = new Set([
      event.service,
      metadata.target_service,
      metadata.source_service,
      ...affectedServices,
    ])
    const noRepairRequired = event.type === 'agent_diagnosis' && event.status === 'no_repair'
    const unsupportedFailure = event.type === 'patch_rejected'
      && (metadata.repair_required === false || event.message?.startsWith('No approved repair exists'))
    if (CLEAR_EVENT_TYPES.has(event.type) || noRepairRequired || unsupportedFailure) {
      services.forEach((service) => {
        if (service) delete incidents[service]
      })
      continue
    }
    let severity = null
    if (FAILURE_EVENT_TYPES.has(event.type) || event.status === 'failed' || event.status === 'unhealthy') {
      severity = 'critical'
    } else if (
      event.type === 'agent_diagnosis'
      || event.type === 'patch_applied'
      || event.type === 'restart_requested'
      || event.type === 'service_started'
      || event.status === 'approval_required'
      || event.status === 'recovering'
    ) {
      severity = 'warning'
    }
    if (severity) {
      services.forEach((service) => {
        if (service) incidents[service] = severity
      })
    }
  }
  return incidents
}

function phaseForEvent(event) {
  if (event.type === 'application_failure' || event.type === 'health_failure') return 'Incident detected'
  if (event.type === 'agent_diagnosis') return event.status === 'no_repair' ? 'Repair unavailable' : 'Diagnosing failure'
  if (event.type === 'patch_rejected' || event.type === 'replay_failed') return 'Recovery blocked'
  if (event.type === 'patch_applied') return 'Patch applied'
  if (event.type === 'repair_pending') return 'Approval required'
  if (event.type === 'restart_requested') return 'Restarting service'
  if (event.type === 'service_started') return 'Starting service'
  if (event.type === 'recovery_failed') return 'Recovery failed'
  if (event.type === 'application_recovered' || event.type === 'service_recovered') return 'Recovered'
  return 'Processing'
}

function activeIncident(events, incidents) {
  const affected = new Set(Object.keys(incidents))
  if (!affected.size) return null
  const event = events.find((candidate) => {
    if (!IMPORTANT_EVENT_TYPES.has(candidate.type)) return false
    const target = candidate.metadata?.target_service
    return affected.has(candidate.service) || (target && affected.has(target))
  })
  if (!event) return null
  const services = [...new Set([event.service, event.metadata?.target_service].filter(Boolean))]
  return {
    event,
    services,
    phase: phaseForEvent(event),
    severity: incidents[event.metadata?.target_service] || incidents[event.service] || 'critical',
    duration: Math.max(0, Date.now() - new Date(event.timestamp).getTime()),
  }
}

function formatDuration(duration) {
  if (duration < 1000) return 'under 1s'
  if (duration < 60000) return `${Math.floor(duration / 1000)}s`
  return `${Math.floor(duration / 60000)}m ${Math.floor((duration % 60000) / 1000)}s`
}

const NODE_WIDTH = 190
const NODE_HEIGHT = 88

function ServiceNode({ data }) {
  return (
    <div className={`graph-node ${data.status} ${data.incident || ''}`}>
      <Handle type="target" position={Position.Left} />
      <div className="graph-node-heading">
        <span className="node-dot" />
        <strong>{data.label}</strong>
      </div>
      <small>{data.incident ? `${data.incident} incident` : data.status}</small>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const nodeTypes = { service: ServiceNode }

function layoutTopology(topology, incidents) {
  const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  graph.setGraph({ rankdir: 'LR', nodesep: 48, ranksep: 100, marginx: 30, marginy: 30 })

  const nodes = (topology.nodes || []).map((node) => ({
    id: node.name,
    type: 'service',
    data: {
      label: node.name,
      status: node.status || 'unknown',
      incident: incidents[node.name],
      details: node,
    },
    position: { x: 0, y: 0 },
  }))
  nodes.forEach((node) => graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT }))

  const edges = (topology.edges || []).map((edge) => {
    const active = edge.status === 'active'
    const incident = incidents[edge.source] || incidents[edge.target]
    const color = incident === 'critical' ? '#ff6e82' : incident === 'warning' ? '#f6b759' : active ? '#78e6b0' : '#5f6d80'
    graph.setEdge(edge.source, edge.target)
    return {
      id: `${edge.source}-${edge.target}`,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      label: incident ? `${incident} incident` : active && edge.last_seen ? `seen ${new Date(edge.last_seen).toLocaleTimeString()}` : 'planned',
      markerEnd: { type: MarkerType.ArrowClosed, color },
      style: { stroke: color, strokeWidth: incident ? 3 : active ? 2.5 : 1.5, strokeDasharray: incident || active ? undefined : '6 5' },
      labelStyle: { fill: color, fontSize: 10, fontFamily: 'var(--mono)' },
      labelBgStyle: { fill: '#101925', fillOpacity: 0.9 },
      data: edge,
    }
  })

  dagre.layout(graph)
  const positionedNodes = nodes.map((node) => {
    const point = graph.node(node.id)
    return { ...node, position: { x: point.x - NODE_WIDTH / 2, y: point.y - NODE_HEIGHT / 2 } }
  })
  return { nodes: positionedNodes, edges }
}

function TopologyGraph({ topology, incidents }) {
  const [selected, setSelected] = useState(null)
  const graph = useMemo(() => layoutTopology(topology, incidents), [topology, incidents])
  const selectedDetails = selected ? topology.nodes.find((node) => node.name === selected) : null

  return (
    <div className="topology-layout">
      <div className="topology-graph">
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => setSelected(node.id)}
          onPaneClick={() => setSelected(null)}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#2c3b4e" gap={24} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <aside className="topology-details">
        <p className="eyebrow">NODE DETAILS</p>
        {selectedDetails ? (
          <>
            <h3>{selectedDetails.name}</h3>
            <p className={`detail-status ${incidents[selectedDetails.name] || selectedDetails.status}`}>
              {incidents[selectedDetails.name] ? `${incidents[selectedDetails.name]} incident` : selectedDetails.status}
            </p>
            <dl>
              <div><dt>Port</dt><dd>{selectedDetails.port}</dd></div>
              <div><dt>Health</dt><dd>{selectedDetails.health}</dd></div>
              <div><dt>Depends on</dt><dd>{selectedDetails.depends_on?.join(', ') || 'none'}</dd></div>
            </dl>
          </>
        ) : (
          <p className="empty-state">Select a node to inspect its registered details.</p>
        )}
      </aside>
    </div>
  )
}

function App() {
  const [state, setState] = useState(initialState)
  const [showAllEvents, setShowAllEvents] = useState(false)

  const incidents = useMemo(() => incidentState(state.events), [state.events])
  const importantEvents = useMemo(
    () => state.events.filter((event) => IMPORTANT_EVENT_TYPES.has(event.type)),
    [state.events],
  )
  const visibleEvents = showAllEvents ? state.events : importantEvents
  const incidentCount = Object.keys(incidents).length
  const incident = useMemo(() => activeIncident(state.events, incidents), [state.events, incidents])

  useEffect(() => {
    let active = true
    let topologyRefreshTimer

    async function loadTopology() {
      const response = await fetch('/api/topology')
      if (!response.ok) throw new Error('Topology API is unavailable')
      return response.json()
    }

    async function loadDashboard() {
      const results = await Promise.allSettled([
        fetch('/api/services').then((response) => {
          if (!response.ok) throw new Error('Service status unavailable')
          return response.json()
        }),
        fetch('/api/events?limit=100').then((response) => {
          if (!response.ok) throw new Error('Event history unavailable')
          return response.json()
        }),
        loadTopology(),
      ])
      if (!active) return
      const [servicesResult, eventsResult, topologyResult] = results
      const failures = results.filter((result) => result.status === 'rejected')
      setState((current) => ({
        ...current,
        ...(servicesResult.status === 'fulfilled' ? { services: servicesResult.value.services } : {}),
        ...(eventsResult.status === 'fulfilled' ? { events: eventsResult.value.events } : {}),
        ...(topologyResult.status === 'fulfilled' ? { topology: topologyResult.value } : {}),
        error: failures.length ? 'Relay connection is reconnecting' : '',
      }))
    }

    function refreshTopologySoon() {
      window.clearTimeout(topologyRefreshTimer)
      topologyRefreshTimer = window.setTimeout(() => {
        loadTopology().then((topology) => {
          if (active) setState((current) => ({ ...current, topology, error: '' }))
        }).catch(() => {})
      }, 250)
    }

    function handleStreamEvent(message) {
      try {
        const event = JSON.parse(message.data)
        setState((current) => ({
          ...current,
          events: [event, ...current.events.filter((item) => item.id !== event.id)].slice(0, 100),
          services: current.services.map((service) =>
            service.name === event.service && event.type === 'service_recovered'
              ? { ...service, status: 'healthy' }
              : service.name === event.service && event.type === 'health_failure'
                ? { ...service, status: 'unhealthy' }
                : service,
          ),
          error: '',
        }))
        refreshTopologySoon()
      } catch (error) {
        if (active) setState((current) => ({ ...current, error: `Invalid relay event: ${error.message}` }))
      }
    }

    loadDashboard()
    const refresh = window.setInterval(loadDashboard, 10000)
    const stream = new EventSource('/api/events/stream')

    stream.onmessage = handleStreamEvent

    stream.onopen = () => {
      if (active) {
        setState((current) => ({ ...current, error: '' }))
        loadDashboard()
      }
    }

    stream.onerror = () => {
      if (active) {
        setState((current) => ({ ...current, error: 'Live event stream disconnected' }))
      }
    }

    return () => {
      active = false
      window.clearInterval(refresh)
      window.clearTimeout(topologyRefreshTimer)
      stream.close()
    }
  }, [])

  async function setupTelemetry() {
    setState((current) => ({ ...current, setup: 'Setting up telemetry…', error: '' }))
    try {
      const response = await fetch('http://127.0.0.1:8000/registry/telemetry/setup', { method: 'POST' })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Telemetry setup failed')
      setState((current) => ({
        ...current,
        setup: result.restart_required
          ? 'Telemetry installed. Restart services to load the decorators.'
          : 'Telemetry is active.',
      }))
    } catch (error) {
      setState((current) => ({ ...current, setup: '', error: error.message }))
    }
  }

  return (
    <main className="dashboard-shell">
      <header className="dashboard-header">
        <div>
          <p className="eyebrow">AUTODECK / CONTROL PLANE</p>
          <h1>Service recovery dashboard</h1>
          <p className="subtitle">A live control room for service health, dependency flow, and safe recovery.</p>
        </div>
        <div className={`connection ${state.error ? 'offline' : 'online'}`}>
          <span /> {state.error ? 'Relay disconnected' : 'Relay connected'}
        </div>
      </header>

      <div className="control-row">
        <button type="button" onClick={setupTelemetry}>Instrument topology</button>
        {state.setup && <span className="setup-status">{state.setup}</span>}
      </div>

      {state.error && <div className="alert">{state.error}</div>}

      <section className="summary-grid" aria-label="System summary">
        <article className="summary-card"><span className="summary-label">Registered services</span><strong>{state.services.length}</strong><small>manifest nodes</small></article>
        <article className="summary-card"><span className="summary-label">Healthy services</span><strong className="good-text">{state.services.filter((service) => service.status === 'healthy').length}</strong><small>responding now</small></article>
        <article className={`summary-card ${incidentCount ? 'summary-alert' : ''}`}><span className="summary-label">Active incidents</span><strong>{incidentCount}</strong><small>{incidentCount ? 'requires attention' : 'no active faults'}</small></article>
        <article className="summary-card"><span className="summary-label">Observed edges</span><strong>{state.topology.edges.filter((edge) => edge.status === 'active').length}</strong><small>runtime paths</small></article>
      </section>

      <section className="section-block hero-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">LIVE TOPOLOGY</p>
            <h2>Service dependency graph</h2>
          </div>
          <span className={`phase-badge ${incident ? incident.severity : 'healthy'}`}>
            <span /> {incident ? incident.phase : 'All systems healthy'}
          </span>
        </div>
        {incident ? (
          <div className={`incident-panel ${incident.severity}`}>
            <div className="incident-icon">!</div>
            <div className="incident-content">
              <div className="incident-topline"><strong>{incident.phase}</strong><span>{formatDuration(incident.duration)} active</span></div>
              <p>{incident.event.message}</p>
              <div className="incident-services">Affected: {incident.services.map((service) => <span key={service}>{service}</span>)}</div>
            </div>
            <time>{new Date(incident.event.timestamp).toLocaleTimeString()}</time>
          </div>
        ) : (
          <div className="healthy-banner"><span className="healthy-check">✓</span><div><strong>All registered services are healthy</strong><p>Runtime dependency edges will activate as requests move through the graph.</p></div></div>
        )}
        <TopologyGraph topology={state.topology} incidents={incidents} />
      </section>

      <details className="technical-panel section-block">
        <summary><span><span className="eyebrow">TECHNICAL DETAILS</span><strong>Registry, service health, and raw events</strong></span><span className="summary-chevron">⌄</span></summary>
        <section className="technical-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">SERVICE REGISTRY</p>
            <h2>Registered services</h2>
          </div>
          <span className="count">{state.services.length} services</span>
        </div>
        <div className="service-grid">
          {state.services.map((service) => (
            <article className={`service-card ${incidents[service.name] || ''}`} key={service.name}>
              <div className="card-topline">
                <div>
                  <p className="service-name">{service.name}</p>
                  <p className="service-entry">127.0.0.1:{service.port}</p>
                </div>
                <span className={`status-pill ${incidents[service.name] || service.status}`}>
                  <span /> {incidents[service.name] ? `${incidents[service.name]} incident` : statusLabel(service.status)}
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

        <section className="events-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">LIVE ACTIVITY</p>
            <h2>Recovery timeline</h2>
          </div>
          <div className="event-controls">
            <span className="count">{visibleEvents.length} shown</span>
            <button type="button" className="filter-button" onClick={() => setShowAllEvents((value) => !value)}>
              {showAllEvents ? 'Important only' : 'Show telemetry'}
            </button>
          </div>
        </div>
        <div className="event-list">
          {visibleEvents.length === 0 ? (
            <p className="empty-state">No actionable recovery events yet. Routine telemetry is being received quietly.</p>
          ) : visibleEvents.map((event) => (
            <article className="event-row" key={event.id}>
              <span className={`event-marker ${event.status}`} />
              <div className="event-main">
                <div className="event-title">
                  <strong>{event.service}</strong>
                  <span>{eventLabel(event.type)}</span>
                </div>
                <p>{event.message}</p>
              </div>
              <time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString()}</time>
            </article>
          ))}
        </div>
        </section>
      </details>
    </main>
  )
}

export default App
