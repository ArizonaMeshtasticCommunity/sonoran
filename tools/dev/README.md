# Local preview

These scripts start the dashboard on your machine, with data in it, so
you can see a change while you make it.

They are for development only. They are not part of the deployment.

## Start it

```bash
./tools/dev/preview.sh
```

The script does these things:

1. It starts the Docker daemon, if the daemon is down.
2. It starts a TimescaleDB container with the name `sonoran-dev-db`.
3. It writes a `.env` file, if there is no `.env` file. Git ignores it.
4. It runs the Alembic migrations.
5. It fills the database with made-up data, if the database is empty.
6. It starts the API with hot reload.

Then open <http://127.0.0.1:8000>.

Set `SONORAN_DEV_PORT` to use a different port.

## What reloads, and when

| You change | What to do |
|------------|------------|
| A file in `src/sonoran/web/static/` | Refresh the browser. The web UI has no build step. |
| A Python file in `src/` | Nothing. Uvicorn restarts the API. Then refresh. |
| A database migration | Stop the script. Start it again. |
| `tools/dev/seed.py` | Run `uv run python tools/dev/seed.py`. Then refresh. |

## The data

`seed.py` writes a made-up mesh of 17 nodes in Arizona. There are
clients in Phoenix, Tucson, Flagstaff, and Prescott. There are routers
on the high ground between them. There are 24 hours of packets,
observations from four gateways, chat messages, telemetry, neighbour
reports, and five traceroutes.

The data is not real. No packet in it crossed a radio.

The random seed is constant. Two runs give the same data. A screenshot
after a change is thus different only because of the change.

To fill the database again:

```bash
uv run python tools/dev/seed.py
```

The script empties the tables before it fills them.

> [!WARNING]
> Do not run `seed.py` against a production database. It deletes the
> contents of every table that it fills.

## Screenshots

`shot.js` takes a picture of a page of the running dashboard. It also
prints the errors that the browser reported.

```bash
node tools/dev/shot.js "/#nodes" /tmp/nodes.png
node tools/dev/shot.js "/#stats" /tmp/stats.png 1920 1080
```

The arguments are the path, the output file, the width, and the
height. Only the path and the output file are necessary.

## A preview you can share

`preview.sh` needs Docker and a checkout. To show a change to someone
who has neither, build a single HTML file that holds the whole
dashboard and a recording of the API:

```bash
./tools/dev/preview.sh                              # in one terminal
node tools/dev/record.js /tmp/recording.json        # in another
node tools/dev/artifact.js /tmp/recording.json /tmp/preview.html
```

The file is about 1.8 MB. It opens in any browser, from a file:// URL,
and it asks nothing of the network.

`record.js` drives the dashboard with a real browser and keeps every
JSON response. It walks each page, changes each filter, and opens the
page of each node and of each traceroute.

`artifact.js` puts the markup, the styles, Leaflet, ECharts, and
`app.js` into one file, with the recording next to them. It replaces
`window.fetch` with a lookup in the recording. A request that was
never recorded falls back to the recording for the same path, so a
filter that was not walked still shows data.

The file has page content only. It has no `<html>`, `<head>`, or
`<body>` tag, so it can be published as a static artifact as it is.

What works in the file: every page in the sidebar, the node pages, the
traceroute pages, the filters, the map, and the graphs. What does not:

- **The clock.** The data is from the moment of the recording. A panel
  that counts the last 15 minutes shows nothing, because that window
  has passed.
- **The coverage planner and the config check.** Both need something
  the file cannot hold. Each says so on its own page.
- **The mesh-graph drawings.** The build removes the links to that
  service, because the file must not ask another host for anything.
- **The map tiles.** The nodes and the links draw on an empty
  background.
- **Save as image.** ECharts offers it, but a published artifact
  cannot hand a file to the viewer.

Rebuild the file after a change to see the change in it.

## What is not in the preview

- **Ingest.** There is no MQTT broker, so no new packets arrive. The
  data does not change until you run `seed.py` again.
- **mesh-graph.** The traceroute drawings come from a separate
  service. The Traceroutes page shows the list, but not the drawing.
- **Map tiles.** The map needs `tile.openstreetmap.org`. The nodes and
  the links draw without the tiles, on an empty background.
- **Daily activity.** The chart reads `daily_snapshot`, which the jobs
  service writes. The chart is empty.
- **Terrain.** The coverage planner needs terrain tiles. Run
  `uv run python tools/prefetch_terrain.py` first. See
  [docs/PLANNER.md](../../docs/PLANNER.md).

## Stop it

Press Ctrl+C. The database container keeps running, and it keeps the
data. To remove it:

```bash
docker rm -f sonoran-dev-db
```
