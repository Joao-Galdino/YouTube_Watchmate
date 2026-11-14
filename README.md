# YouTube Watchmate

**YouTube Watchmate is a YouTube transcript companion for AI assistants.** It helps an assistant answer questions about what a video says, find relevant passages, and return timestamp links. Its provider priority is **saved transcript cache → yt-dlp captions → optional SerpApi fallback**. Local mode works without a SerpApi token.

## Install

Copy the `watchmate` folder to `~/.codex/skills/` or `$CODEX_HOME/skills/`, then open a new Codex session. Copying the folder does not run anything, contact external services, or start a conversation. Python 3.10 or newer is required.

YouTube Watchmate uses yt-dlp from its own `.venv` first and otherwise from `PATH`. To install the pinned local dependency without changing global packages, run from the `watchmate` folder:

macOS/Linux:

```bash
python3 -m venv .venv && .venv/bin/python -m pip install --isolated 'yt-dlp==2026.10.26'
```

Windows PowerShell:

```powershell
py -m venv .venv; .venv\Scripts\python -m pip install --isolated "yt-dlp==2026.10.26"
```

Check availability without network access or reading a token:

```bash
python3 scripts/transcript.py status
```

## Optional SerpApi fallback

SerpApi is not required for local use. If enabled, it uses the recipient's own account and may consume that account's quota. Configure the token privately with `SERPAPI_API_KEY`, `SERPAPI_API_KEY_FILE`, or `--key-file`; never paste it into chat or pass it as a command argument. A key file contains only the token and should be readable only by its owner.

The default key file is `$XDG_CONFIG_HOME/watchmate/api_key` (otherwise `~/.config/watchmate/api_key`) on macOS/Linux, or `%APPDATA%/watchmate/api_key` on Windows. The former `codex-youtube-transcript/api_key` default remains a compatibility fallback. To force local-only behavior, use `--fallback off`, `--provider yt-dlp`, or set `YOUTUBE_TRANSCRIPT_FALLBACK=off`.

## Use

In Codex, share a YouTube link and ask what the video says, request a summary, or ask about a specific passage. YouTube Watchmate activates for video-content questions even when the user does not explicitly request a transcript. Transcript evidence covers spoken content; silent on-screen actions require separate visual evidence.

From the terminal:

```bash
python3 scripts/transcript.py fetch 'https://www.youtube.com/watch?v=VIDEO_ID' --output-dir ./captions
python3 scripts/transcript.py search ./captions/VIDEO_ID.en.default.json --terms Airflow --context 2
```

Saved results include normalized JSON and timestamped text and are reused without network access. The helper does not download audio or video, use cookies, load user yt-dlp configuration/plugins, or retry indefinitely. SerpApi is called at most once per invocation and only when enabled and configured.

MIT licensed. yt-dlp is installed separately under its own license, and video captions remain subject to their respective rights.
