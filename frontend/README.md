# PaperLab frontend (SvelteKit)

Modern Svelte replacement for the Streamlit UI in `app/`. Layout follows the
approved reference (sidebar + topbar + stat cards) re-skinned to the Archive
Reading Room tokens in `src/app.css` (which mirror `DESIGN.md`).

## Run

Follow the [root setup guide](../README.md) for macOS, Windows, and Linux.
Use Node 24 LTS and `npm ci`. `npm run dev` serves port 5173 and proxies
`/api` to FastAPI on port 8000. `npm run build` writes `frontend/build/`,
which FastAPI serves directly in production. On Windows PowerShell use
`npm.cmd` if script execution is disabled.

## Structure (best-practice SvelteKit)

```text
frontend/
  src/
    app.css                 # design tokens + base styles (light/dark)
    app.html
    lib/
      api.js                # REST client; 1:1 with BACKEND_CONTRACT.md
      stores.js             # theme, role, searchQuery (localStorage-backed)
      components/
        Sidebar.svelte      # brand, nav, status ledger, role switch
        Topbar.svelte       # breadcrumb, role pill, Ctrl+K search, theme toggle
        StatCard.svelte     # stat tiles
        PaperCard.svelte    # archive catalog card
        SegmentedTabs.svelte# pill tabs (Stage / Verify / Pipeline)
    routes/
      +layout.svelte        # shell: sidebar + topbar + content
      +page.svelte          # redirect to /archive
      archive/              # Archive wall (everyone)
      archive/[id]/         # Reading Desk (everyone reads; archivist edits)
      inbox/                # Tagging Inbox (archivist)
      syllabus/             # Syllabus Map (archivist)
      intake/               # Intake and Pipeline (archivist)
      ledger/               # Usage Ledger (archivist)
```

## Roles

`role` store (`student` | `archivist`) only hides edit UI. Real enforcement
must happen server-side on every admin endpoint — see BACKEND_CONTRACT.md.

See [BACKEND_CONTRACT.md](BACKEND_CONTRACT.md) for the FastAPI routes.
