# Status page

A live page built from this repository: tickets by owner, open pull requests and their review state,
CI, the data in the bucket, the critical path and recent activity. It rebuilds on every push to `main`,
on issue, pull request and review events, after CI runs, and every 15 minutes. Open
https://aidaneichman.github.io/ac215_Undersigned/ .

Nothing is typed in for the numbers. A ticket is an issue titled `U-NN ...`:

| Status | When |
|---|---|
| done | the issue is closed |
| in review | an open pull request mentions it ("Closes #6", "Refs #3", "Part of #14") |
| started | it has the `started` label |
| not started | none of the above |

To keep the page right: put `started` on a ticket when you begin it, close it when it is done, and write
`Closes #N` in the pull request.

The judgment calls are in `plan.json`: blockers, the critical path (each box can point at a ticket and takes
its colour from it), next steps, and a few facts. Edit the file and push.

To preview locally: `GITHUB_TOKEN=$(gh auth token) OUT_DIR=/tmp/site python3 status/build_status.py`, then open
`/tmp/site/index.html`. The script uses only the standard library.
