# ScreenTracker — TV, Film, Game & Video Library

A Flask web app for managing a personal library of TV shows, movies, video
games and YouTube videos, with search powered by **The Movie Database (TMDB)**
and **IGDB**. Each title is grouped into a genre (you can create new genres on
the fly) — except YouTube videos, which get their own section. The library is
stored locally in SQLite.

## Features

- 🔍 **Live search** across TMDB movies and TV series plus IGDB games as you type
- 🎬 **Rich previews** in search results: poster, year, network, country, overview
- 🎮 **Game support** with cover art, developer, release year and genre, alongside TV and film
- 📺 **YouTube videos** added by URL, kept in their own section with thumbnail, channel and year
- 📁 **Genre grouping** — pick an existing genre or create a new one when adding
- 🔄 **Move titles** between genres
- 🗑️ **Delete** titles or whole genres
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

4. **Get IGDB credentials** (optional, free for non-commercial use) to search games:

   - Sign up for a Twitch account with 2FA enabled
   - Create an application at https://dev.twitch.tv/console/apps
     - **OAuth Redirect URL:** any value, e.g. `http://localhost:1234` — IGDB
       uses the server-to-server `client_credentials` grant, so this is never used
     - **Category:** Application Integration
     - **Client Type:** Confidential (required to generate a Client Secret)
   - Generate a Client Secret and copy the Client ID

5. **Set the IGDB credentials:**

   ```bash
   export IGDB_CLIENT_ID="your-client-id"
   export IGDB_CLIENT_SECRET="your-client-secret"
   ```

   Without these, search silently skips games and returns TV/film results only.
   Add them to `.env` to persist across restarts (the app calls `load_dotenv()`).

6. **Get a YouTube API key** (optional, free within quota) to add videos:

   - Create a project in the [Google Cloud Console](https://console.cloud.google.com/)
   - Enable **YouTube Data API v3**
   - Create an API key under **Credentials** (restrict it to the YouTube Data API)

   Only `videos.list` is called, which costs **1 quota unit** of the free
   **10,000 per day** allowance, so a personal library will never come close.

7. **Set the YouTube API key:**

   ```bash
   export YOUTUBE_API_KEY="your-api-key"
   ```

   Without it the YouTube tab in "Add manually" shows a hint and refuses to add
   videos; everything else still works.

8. **Run the app:**

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

- **`app.py`** — Flask routes + TMDB/IGDB/YouTube integration + SQLite persistence
- **`lib/tmdb.py`** — TMDB client and response normalization
- **`lib/igdb.py`** — IGDB client, Twitch app-token caching and normalization
- **`lib/youtube.py`** — YouTube Data API client, URL/video-id parsing and normalization
- **`templates/index.html`** — Main page rendering grouped titles
- **`static/app.js`** — Search, modals, and card actions
- **`static/style.css`** — Styling
- **`db/shows.db`** — Auto-created SQLite database (the Docker volume mount)

## API endpoints

| Method | Path                    | Purpose                             |
|--------|-------------------------|-------------------------------------|
| GET    | `/api/search?q=...`     | Search TMDB and IGDB together       |
| GET    | `/api/genres`           | List genres                         |
| POST   | `/api/genres`           | Create a genre                      |
| DELETE | `/api/genres/<id>`      | Delete a genre (shows un-grouped)   |
| POST   | `/api/shows`            | Add a title (creates genre if new)  |
| PUT    | `/api/shows/<id>/genre` | Move a title to another genre       |
| DELETE | `/api/shows/<id>`       | Remove a title                      |

## Notes

- TMDB multi-search returns people as well as titles; the app filters results to
  series and movies only.
- The two search sources are queried independently, so one being down still
  returns the other's results. Partial failures are reported under an `errors` key.
- YouTube videos are **not** part of the main search box. They are added from the
  **YouTube** tab of the "Add manually" dialog by pasting a video URL or an
  11-character video ID. `watch?v=`, `youtu.be/`, `/shorts/`, `/embed/`,
  `/live/` and `/v/` links all work.
- YouTube videos are stored with `media_type = 'youtube'` and a `NULL` genre, so
  they render in their own section instead of inside a genre or the
  "Uncategorised" bucket, and they offer no genre action.
- All four media types share one `shows` table: `media_type` is part of the
  uniqueness key alongside the source id, so a TMDB id and an IGDB id that happen
  to match cannot collide. No schema change was needed for videos.
- IGDB is queried with `game_type = (0,4,8,9,10,11,12)` and
  `version_parent = null`, which keeps main games, remakes, remasters and ports
  while dropping DLC, expansions, bundles, mods, packs and store editions.
- IGDB retired the `status` and `category` game fields, so the release status is
  derived from `first_release_date` (`Released` / `Upcoming`).
- IGDB provides no IMDb id and no country of origin, and YouTube provides
  neither, so those fields stay empty and the card's IMDb link is omitted.
- The channel name and developer are only shown while searching, not on saved
  cards: the `shows` table has no column for them.
- Metadata is refreshed from TMDB, IGDB or the YouTube API when a search result
  or video is added.
- TMDB and IGDB data and images are attributed in the application footer as
  required.
