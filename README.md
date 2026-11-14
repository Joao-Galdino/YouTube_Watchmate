# YouTube Watchmate

**YouTube Watchmate is a YouTube transcript companion for AI assistants.** It helps an assistant answer questions about what a video says, find relevant passages, and return timestamp links. Its provider priority is **saved transcript cache → yt-dlp captions → optional SerpApi fallback**. Local mode works without a SerpApi token.

## Install with your agent

This repository follows the open [Agent Skills specification](https://agentskills.io/specification). The skill lives in `watchmate/`, with the matching technical name `watchmate`, so compatible installers can include its helper script.

The primary installation flow is to paste this repository URL into a local coding agent that supports Agent Skills, such as Codex or Claude Code, and ask it to install the skill. Installing the files requires **no Node.js, npm, npx, GitHub CLI, Python, yt-dlp, or SerpApi account**.

```text
Install the Agent Skill `watchmate` from https://github.com/Joao-Galdino/YouTube_Watchmate for my user account. Review `watchmate/SKILL.md` and `watchmate/scripts/transcript.py` first. Do not install Node.js, npm, npx, or GitHub CLI for this skill, and do not stop merely because those optional tools are absent. Use your native skill installer if available. Otherwise, download the public repository archive with existing OS or Python tools, extract it in a temporary location, and place only the `watchmate` directory in the documented personal Agent Skills directory for this client. Do not run transcript retrieval, install runtime dependencies, or configure SerpApi unless I ask.
```

Codex includes a skill installer that can download skills from other repositories; see the [official Codex skills documentation](https://learn.chatgpt.com/docs/build-skills). Claude Code implements the same open format; see the [official Claude Code skills documentation](https://code.claude.com/docs/en/skills).

### Native fallback for the installing agent

If a native installer cannot handle the URL, the agent should complete the file installation itself without adding package managers:

1. Download `https://github.com/Joao-Galdino/YouTube_Watchmate/archive/refs/heads/main.zip` with an already available OS download tool or Python's standard library.
2. Extract it to a temporary directory and inspect `watchmate/SKILL.md` and `watchmate/scripts/transcript.py`.
3. Copy the extracted `watchmate` directory, preserving `scripts/transcript.py`, to the target client's documented personal skills location:
   - Codex: `$HOME/.agents/skills/watchmate`
   - Claude Code: `~/.claude/skills/watchmate`
   - Other Agent Skills clients: use that client's official user-scope skills directory; do not guess a path.
4. Start a new agent session if the skill does not appear immediately.

These destinations come from the [official Codex](https://learn.chatgpt.com/docs/build-skills) and [Claude Code](https://code.claude.com/docs/en/skills) documentation. The fallback is work performed by the installing agent, not a requirement for the recipient to copy files manually.

Opening the repository URL does not install or execute anything by itself. A generic web chat may not have access to a local skill directory or shell, so use a compatible local agent/client and review its proposed file changes before approving installation.

### Optional installer CLIs

These are conveniences only when already installed. **Do not install Node.js/npm/npx or GitHub CLI solely to install Watchmate.** GitHub CLI provides `gh skill` in preview:

```bash
gh skill install Joao-Galdino/YouTube_Watchmate watchmate --agent codex --scope user
gh skill install Joao-Galdino/YouTube_Watchmate watchmate --agent claude-code --scope user
```

See the official [`gh skill install` reference](https://cli.github.com/manual/gh_skill_install). If `npx` is already available, the `skills` CLI can install from the same URL and prompt for a target agent:

```bash
npx skills add https://github.com/Joao-Galdino/YouTube_Watchmate --skill watchmate --global
```

To target both Codex and Claude Code explicitly:

```bash
npx skills add https://github.com/Joao-Galdino/YouTube_Watchmate --skill watchmate --global --agent codex --agent claude-code
```

See the [`skills add` CLI reference](https://github.com/vercel-labs/skills/blob/main/docs/commands.md). Absence of either optional CLI is not an installation blocker. These installers place the skill where the selected local agent can discover it; they do not run Watchmate or configure SerpApi.

## Runtime requirements and optional local captions setup

Installing the skill files does not require Python. Running Watchmate's helper requires Python 3.10 or newer. Local caption retrieval additionally uses yt-dlp, while saved transcript reuse and SerpApi configuration remain separate concerns.

YouTube Watchmate uses yt-dlp from its own `.venv` first and otherwise from `PATH`. Only when local caption retrieval is wanted, run from the installed `watchmate` skill directory to install the pinned dependency without changing global packages:

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

SerpApi is not required for local use, and it is not guaranteed to have a transcript for every video. If you previously chose local-only operation, keep that preference until you explicitly decide to enable this fallback.

1. Review SerpApi's [current plans, prices, and limits](https://serpapi.com/pricing), then optionally create an account on the [official signup page](https://serpapi.com/users/sign_up). Successful uncached requests may consume account quota or incur cost under the selected plan; Watchmate does not subscribe, buy credits, or assume a free allowance.
2. Retrieve the private token from SerpApi's [API-key dashboard](https://serpapi.com/manage-api-key). Never paste the token into an agent chat, issue, README, or command argument.
3. Store only the token in the supported private key file: `$XDG_CONFIG_HOME/watchmate/api_key` (otherwise `~/.config/watchmate/api_key`) on macOS/Linux, or `%APPDATA%/watchmate/api_key` on Windows. On macOS/Linux, make the directory owner-only (mode 700) and the file owner-readable/writable (mode 600). Alternatively, point `SERPAPI_API_KEY_FILE` or `--key-file` at an equivalently protected file; `SERPAPI_API_KEY` is supported but is easier to expose accidentally.
4. Run `python3 scripts/transcript.py status` from the installed skill directory. It reports whether a credential is present without reading key-file contents, validating the credential, or making a network request.
5. Only after choosing to use the fallback, retry with the default `--provider auto --fallback auto` and ensure `YOUTUBE_TRANSCRIPT_FALLBACK=off` is not set. Watchmate preserves the exact sequence **saved cache → one bounded, no-retry yt-dlp captions attempt → at most one configured SerpApi request**. To remain local-only, keep `--fallback off`, `--provider yt-dlp`, or `YOUTUBE_TRANSCRIPT_FALLBACK=off`.

The former `codex-youtube-transcript/api_key` default remains a compatibility fallback. See the official [YouTube Video Transcript API documentation](https://serpapi.com/youtube-video-transcript) for the provider contract. If you do not want to configure SerpApi, provide a transcript, SRT/VTT file, or relevant passage instead. Running the helper still requires Python 3.10+; this setup does not require Node.js or npm.

## Optional integrated-browser accompaniment

When the host agent exposes an integrated browser, Watchmate can accompany a supplied YouTube link: it checks the tabs exposed by that browser for the same canonical video ID, reuses a matching tab, and otherwise opens the validated user-supplied video. This avoids duplicating an already-open watch, shorts, live, embed, or `youtu.be` link. No separate “open it” request is needed unless the user has opted out of browser use.

This is capability-dependent: Codex, Claude, and other Agent Skills clients do not all expose the same browser tools. Watchmate does not inspect browser profiles, cookies, history, or unexposed tabs; install extensions; or silently substitute an unrelated external browser. If the integrated surface is absent, it simply continues transcript work. It does not autoplay, click play, seek, change the timestamp, close tabs, open discovery results, or follow links found in captions unless explicitly requested. Opening a page is not evidence that the assistant viewed the video; spoken-content answers remain grounded in transcripts, while silent visual details require separate visual evidence.

## Use

In Codex, share a YouTube link and ask what the video says, request a summary, or ask about a specific passage. YouTube Watchmate activates for video-content questions even when the user does not explicitly request a transcript. Transcript evidence covers spoken content; silent on-screen actions require separate visual evidence.

From the terminal:

```bash
python3 scripts/transcript.py fetch 'https://www.youtube.com/watch?v=VIDEO_ID' --output-dir ./captions
python3 scripts/transcript.py search ./captions/VIDEO_ID.en.default.json --terms Airflow --context 2
```

Saved results include normalized JSON and timestamped text and are reused without network access. The helper does not download audio or video, use cookies, load user yt-dlp configuration/plugins, or retry indefinitely. SerpApi is called at most once per invocation and only when enabled and configured.

MIT licensed. yt-dlp is installed separately under its own license, and video captions remain subject to their respective rights.
