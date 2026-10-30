# How we work

Five of us, one repo. The course says every one of us has to explain every part of the project, so the
process below is built to spread understanding as well as code.

## Tickets and pull requests

- Work from the [board](https://github.com/users/aidaneichman/projects/1). One ticket, one branch, one pull
  request, and the PR says `Closes #N`.
- Branch from `main` and open the PR against `main`. For a submission we cut a `milestoneN` branch from
  `main` and hand in its commit hash.
- Keep a PR to one idea. A reviewer should be able to read it in a sitting.

## Review

The reviewer is the owner of the code that uses yours, because they are the one who finds out first if the
contract is wrong.

| Code | Reviewed by |
|---|---|
| data-collector | Andrew |
| data-processor | Aadil |
| campaign-builder | Andrew |
| rule-passages | Rishi |
| api-service, frontend | Aidan |

The reviewer asks questions as well as leaving comments. If you cannot explain a line you merged, it is not
finished.

## Before you open a PR

- Run your container's tests and linter. `rule-passages/` is the model: `cd rule-passages && uv run pytest && uv run ruff check .`.
  Copy its `[dependency-groups]` and ruff settings into your `pyproject.toml`.
- Rebuild your container and run it alone: `docker compose run --rm <container>`.
- Add a short section for your container to the README (what it reads, what it writes, how to run it) and put
  logs and one real input and output under `docs/evidence/<container>/`.
- Write commit messages in your own words: a short imperative first line, then why, when the why is not obvious.

## What never goes in git

- API keys, `.env`, anything in `secrets/`.
- Data. It goes through DVC (`uv run dvc pull` to get it, see the README for versions).
- Personal details from comments or signer lists: names, places, addresses. We rank campaigns, never people,
  and signer names are hashed.

## Numbers

A number goes in a document only after we have checked it against the data. If a figure from the MS1
proposal does not reproduce, say so next to it.
