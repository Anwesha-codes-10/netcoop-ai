# NetCoop AI frontend

Vanilla HTML, CSS and JS. No build step, no npm, no dependencies.

    frontend/
    ├── index.html          page shell
    ├── css/styles.css      Obsidian & Cybernetic NOC theme (tokens in :root)
    ├── js/
    │   ├── config.js       agent colours, tabs, shared state
    │   ├── api.js          fetch helpers for /api
    │   ├── ui.js           small shared helpers
    │   ├── sidebar.js      scenarios, upload, saved incidents
    │   ├── views/          shell, diagnosis, trace, telemetry, topology, report, benchmark
    │   └── main.js         boot
    └── README.md

Put this folder at the repo root, next to `netcoop/`, then run `netcoop serve`
and open the address it prints. The API mounts `frontend/` at `/` and the page
calls `/api/*` on the same origin. Scripts load in the order listed in index.html.
