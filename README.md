# ScreenTracker — TV Show & Movie Library

A Flask web app for managing a personal library of TV shows and movies, with
search powered by **TheTVDB API**. Each item is grouped into a genre (you can
create new genres on the fly), and the library is stored locally in SQLite.

## Features

- 🔍 **Live search** via TheTVDB v4 API as you type
- 🎬 **Rich previews** in search results: poster, year, network, country, overview
- 📁 **Genre grouping** — pick an existing genre or create a new one when adding
- 🔄 **Move shows** between genres
- 🗑️ **Delete** shows or whole genres
- 🎨 Dark, magazine-style UI

## Setup

1. **Install dependencies:**

   ```bash
   python3 -m venv .venv 
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Get a TVDB API key** (free for personal use):

   - Sign up at https://thetvdb.com
   - Go to https://thetvdb.com/api-information and create a project key
   - Some keys also need a "subscriber PIN" — only set this if your key requires it

3. **Set the API key** as an environment variable:

   ```bash
   export TVDB_API_KEY="your-api-key-here"
   ```

4. **Run the app:**

   ```bash
   python app.py
   ```

   Then open http://localhost:1234 in your browser.

## How it works

- **`app.py`** — Flask routes + TVDB API client + SQLite persistence
- **`templates/index.html`** — Main page rendering grouped shows
- **`static/app.js`** — Search, modals, and card actions
- **`static/style.css`** — Styling
- **`shows.db`** — Auto-created SQLite database (in the project folder)

## API endpoints

| Method | Path                              | Purpose                           |
|--------|-----------------------------------|-----------------------------------|
| GET    | `/api/search?q=...`               | Search TVDB                       |
| GET    | `/api/genres`                     | List genres                       |
| POST   | `/api/genres`                     | Create a genre                    |
| DELETE | `/api/genres/<id>`                | Delete a genre (shows un-grouped) |
| POST   | `/api/shows`                      | Add a show (creates genre if new) |
| PUT    | `/api/shows/<id>/genre`           | Move a show to another genre      |
| DELETE | `/api/shows/<id>`                 | Remove a show                     |

## Notes

- TVDB tokens are cached in memory for 25 days. The app refreshes
  automatically.
- The TVDB v4 search returns mixed types — this app filters to series and
  movies only.
- IMDb URLs come from TVDB's `remote_ids` when available.
