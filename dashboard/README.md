# AutoDeck dashboard

The dashboard is a React/Vite client for the AutoDeck relay and control plane. It shows the live service topology, health state, runtime-observed dependency edges, incident highlighting, recovery progress, and an expandable technical event view.

## Start

From this directory:

```bash
npm install
npm run dev
```

The development server normally runs on `http://localhost:5173`. Start the backend first from the repository root:

```bash
make demo-up
```

The Vite development proxy forwards `/api` requests to the relay on `http://127.0.0.1:8005`. The dashboard also calls the control-plane registry endpoint on port `8000` for the `Instrument topology` action.

## Useful commands

```bash
npm run lint
npm run build
npm run preview
```

## Dashboard behavior

- All manifest services are shown as nodes.
- Planned dependencies are dimmed and dashed until traffic observes them.
- Active dependency edges show their latest observation time.
- Healthy nodes are green; warning/recovery states are amber; failures are red; unknown state is gray.
- The default view keeps routine telemetry out of the main timeline.
- Technical details expose the complete SSE event history and manifest information.
- `Instrument topology` explicitly starts the backend registry flow; loading the dashboard does not edit source files.

The dashboard consumes the relay SSE stream at `/events/stream` and refreshes topology after relevant telemetry, health, and recovery events.
