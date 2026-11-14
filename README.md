# YouTube Watchmate

**YouTube Watchmate is a YouTube transcript companion for AI assistants.** It helps an assistant answer questions about what a video says, find relevant passages, and return timestamp links. Its provider priority is **saved transcript cache → yt-dlp captions → optional SerpApi fallback**. Local mode works without a SerpApi token.

## Install with your agent

This repository follows the open [Agent Skills specification](https://agentskills.io/specification). The skill lives in `watchmate/`, with the matching technical name `watchmate`, so compatible installers can include its helper script.

The primary installation flow is to paste this repository URL into a local coding agent that supports Agent Skills, such as Codex or Claude Code, and ask it to install the skill:

```text
Install the Agent Skill `watchmate` from https://github.com/Joao-Galdino/YouTube_Watchmate for my user account. Review SKILL.md and scripts/transcript.py before installing. Use your supported skill installer. Do not run transcript retrieval or configure SerpApi unless I ask.
```

Codex includes a skill installer that can download skills from other repositories; see the [official Codex skills documentation](https://learn.chatgpt.com/docs/build-skills). Claude Code implements the same open format; see the [official Claude Code skills documentation](https://code.claude.com/docs/en/skills).

Opening the repository URL does not install or execute anything by itself. A generic web chat may not have access to a local skill directory or shell, so use a compatible local agent/client and review its proposed file changes before approving installation.

### CLI alternatives

GitHub CLI provides `gh skill` in preview. Install for one user account with the command matching the target agent:

```bash
gh skill install Joao-Galdino/YouTube_Watchmate watchmate --agent codex --scope user
gh skill install Joao-Galdino/YouTube_Watchmate watchmate --agent claude-code --scope user
```

See the official [`gh skill install` reference](https://cli.github.com/manual/gh_skill_install). If your GitHub CLI does not provide `gh skill`, the supported `skills` CLI can install from the same URL and prompt for a target agent:

```bash
npx skills add https://github.com/Joao-Galdino/YouTube_Watchmate --skill watchmate --global
```

To target both Codex and Claude Code explicitly:

```bash
npx skills add https://github.com/Joao-Galdino/YouTube_Watchmate --skill watchmate --global --agent codex --agent claude-code
```

See the [`skills add` CLI reference](https://github.com/vercel-labs/skills/blob/main/docs/commands.md). These installers place the skill where the selected local agent can discover it; they do not run Watchmate or configure SerpApi.

## Optional local captions setup

Python 3.10 or newer is required. YouTube Watchmate uses yt-dlp from its own `.venv` first and otherwise from `PATH`. From the installed `watchmate` skill directory, install the pinned local dependency without changing global packages:

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
