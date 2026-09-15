# Privacy

Easy Sync does not upload audio, Wwise projects, source paths, settings or logs.
Wwise integration uses WAAPI (localhost by default). Instance IPC uses localhost TCP.

GitHub is contacted only when the user requests an update check/download. GitHub
receives normal request metadata such as IP address and the version in User-Agent.
No GitHub account or token is required by the installed app. No telemetry is sent.

Source-file absolute paths are recorded in Wwise Sound Notes for original-file lookup.
Those Notes travel with a shared Wwise project. Local settings and logs can contain
project names and paths; review them before sharing a bug report.

The public repository and release exclude development audio, private projects,
logs, screenshots, backups, credentials and local development notes.
