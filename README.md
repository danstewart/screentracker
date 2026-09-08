# ScreenTracker — TV Show & Movie Library

A Flask web app for managing a personal library of TV shows and movies, with
search powered by **The Movie Database (TMDB) API**. Each item is grouped into a genre (you can
create new genres on the fly), and the library is stored locally in SQLite.

## Features

- 🔍 **Live search** across TMDB movies and TV series as you type
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

2. **Get a TMDB application credential** (free for non-commercial use):

   - Sign up at https://www.themoviedb.org
   - Open https://www.themoviedb.org/settings/api and request API access
   - Copy the **API Read Access Token** (recommended), or the v3 API key

3. **Set the API key** as an environment variable:

   ```bash
   export TMDB_API_TOKEN="your-read-access-token-here"
   ```

   Alternatively, set `TMDB_API_KEY` to your v3 API key.

4. **Run the app:**

   ```bash
   python app.py
   ```

   Then open http://localhost:1234 in your browser.

## Deploy

```
git pull
docker compose -f docker-compose.yml up -d --build
```

## How it works

- **`app.py`** — Flask routes + TMDB integration + SQLite persistence
- **`lib/tmdb.py`** — TMDB client and response normalization
- **`templates/index.html`** — Main page rendering grouped shows
- **`static/app.js`** — Search, modals, and card actions
- **`static/style.css`** — Styling
- **`db/shows.db`** — Auto-created SQLite database (the Docker volume mount)

## API endpoints

| Method | Path                              | Purpose                           |
|--------|-----------------------------------|-----------------------------------|
| GET    | `/api/search?q=...`               | Search TMDB                       |
| GET    | `/api/genres`                     | List genres                       |
| POST   | `/api/genres`                     | Create a genre                    |
| DELETE | `/api/genres/<id>`                | Delete a genre (shows un-grouped) |
| POST   | `/api/shows`                      | Add a show (creates genre if new) |
| PUT    | `/api/shows/<id>/genre`           | Move a show to another genre      |
| DELETE | `/api/shows/<id>`                 | Remove a show                     |

## Notes

- TMDB multi-search returns people as well as titles; the app filters results to
  series and movies only.
- Metadata is refreshed from TMDB when a search result is added.
- TMDB data and images are attributed in the application footer as required.
