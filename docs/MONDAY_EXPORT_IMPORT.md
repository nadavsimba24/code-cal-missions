# Exporting a monday board and importing it into CODE-CAL MISSIONS

**Date:** 08.10.2026 · **Version:** 1.0 · **Audience:** whoever runs the migration
**Purpose:** how to get a board out of monday, how to join the responses into one file, and what to check before and after the upload.

> Every number here comes from a real migration: the board **ניהול פרויקטים 2025** (`6257071922`) —
> 320 items, 71 sub-items, 605 conversations, 8,959 history entries.

---

## 1. Why three requests and not one

The import reads monday's API response, not an Excel export: an xlsx has lost the column types by the
time it is written, and the import would be guessing at every column. The queries live in
[backend/monday_export.graphql](../backend/monday_export.graphql); anyone running them through Postman
imports [backend/monday_export.postman_collection.json](../backend/monday_export.postman_collection.json).

| # | Request | What it brings | When to run it |
|---|---|---|---|
| 1 | **The board** | name, groups, column definitions, 500 items, sub-items, conversations, files | always |
| 2 | **The history** | `activity_logs` — who changed what and when — and the account's user list | always |
| 3 | **Next page** | the rest of the items, by `cursor` | only if the board is longer than 500 rows |

The history is a request of its own because it does not fit beside 500 items: a 320-item board came
back `REQUEST_MAX_COMPLEXITY_EXCEEDED` at cost 5,125,801 against monday's ceiling of 5,000,000.

> ⚠ **One request carries one operation.** `monday_export.graphql` holds three. A request carrying two
> comes back HTTP 200 with `operation name is required when multiple operations are defined` — an error
> that reads like a dead token. Postman's query box *appends* what is pasted instead of replacing it,
> and it scrolls, so a second query can sit below the visible lines and look deleted. That is what the
> collection is for: each of its requests already holds exactly one operation.

---

## 2. The one failure monday does not report

`boards(ids: $boardId)` with an empty variable is `boards(ids: [])`, and monday answers that **exactly
as it answers `ids: null`**: the first 25 boards in the account, HTTP 200, no error.

This is what it looks like — a real history response that came back that way:

```
boards: 25
  18374015793  logs: 10000
  18382373316  logs:  4251
  ...                                ← 20,064 entries belonging to 25 boards
  6581100288   logs:     7           ← and the board asked for, 6257071922, is not among them
```

The requested board was older than all 25 that came back, so it fell below the first page. The file
looked full — 15MB of logs — and held not one line belonging to the board being migrated.

**Why it happens even when the variable "is filled in":** the GraphQL body says
`{"boardId": [{{boardId}}]}`. If the variable has only an *Initial value* and no *Current value*, or it
is defined in a collection other than the one you sent from, what goes out is `[]`.

**How to avoid it:** the collection in this repo stops the request before it is sent when `boardId` is
empty, and checks that the answer holds exactly one board — the one you asked for. Running outside the
collection, the safest thing is to drop the variable and put the id in the query:

```graphql
boards(ids: [6257071922]) { ... }
```

**How to check a file you already have:** there must be exactly one board in the response.

```bash
python -c "
import json,sys
d=json.load(open(sys.argv[1]))
for i,r in enumerate(d if isinstance(d,list) else [d]):
    b=(r.get('data') or {}).get('boards') or []
    print(i, 'boards:', len(b), [x.get('id') for x in b][:3])
" board.json
```

`boards: 1` — good. `boards: 25` — the request did not filter; run it again.

---

## 3. The process, step by step

### Step 1 — the board

1. In Postman: import the collection, then open the collection's **Variables** — `MONDAY_TOKEN` and
   `boardId` (the board's id, from its URL). Fill the **Current value** column, not only Initial.
2. Run request 1 and save the response as `board.json`.
3. Check `cursor` in the response: if it is **not** `null`, the board is longer than 500 rows — run
   request 3 with that cursor, again and again, until `cursor` comes back `null`. Save every response.

### Step 2 — the history

Run request 2 and save it as `log.json`. It also brings `users`; without that every row in the log reads
"מערכת" (system), because monday's log names a person by user id and never by name.

If exactly **10,000** entries came back, that is the query's limit and there may be more. Run it again
with `page: 2`: if the answer is `[]` you have everything; if not, that response goes into the file too.

### Step 3 — the merge

All the responses go into one file, as a JSON array. Order does not matter — the import reads them as
the one board they describe:

```json
[ {the board response}, {the history response}, {page 2}, {page 3} ]
```

```bash
python scripts/merge_monday_export.py board.json log.json -o merged.json
```

The script is the wrapper and the checks before the upload, in one run: how many items, history rows
and users each response brought, which board each one is about, and then — the things that otherwise
surface only after the import — whether a cursor was left open mid-board, whether the history belongs
to other boards (section 2), whether a history page came back at its 10,000 ceiling, and whether the
file links have already expired. It refuses to write when the import would hit a wall, and refuses to
overwrite an existing target without `--force`.

Checking a merged file you already have, writing nothing:

```bash
python scripts/merge_monday_export.py merged.json --check
```

> The merge is the wrapper and nothing else — `[`, a comma, `]`. It does not repair a response that came
> back wrong, and a stale response mixed in with a fresh one produces a file that looks perfectly fine:
> nothing in the file says when it was fetched, so that is the one thing the checks cannot see for you.

### Step 4 — the upload

In the app: **+** in the sidebar → **לוח** (board) → **יצירת לוח מקובץ** (create a board from a file),
and choose `merged.json`. The same thing sits in an existing board's menu under *ייבוא לוח מקובץ*. You
can type a name; without one the board arrives under its own name from monday. Both routes are desktop
only — the import is not offered on a phone — and both need the create-board permission.

---

## 4. What to check in the import report

The report opens as soon as the import finishes, and can be saved as a PDF. These are the lines that
change what you do next:

| In the report | What it means | What to do |
|---|---|---|
| **הקובץ אינו הלוח המלא** (the file is not the whole board) | `cursor` still had a value — the export stopped mid-board | collect the remaining pages (request 3) and import again |
| **בקובץ היו עוד N לוחות** (the file held N more boards) | a request ran without `boardId`; those boards' history was left behind | run the history request again with the id |
| **היסטוריית הלוח לא יובאה** (no history imported) | either the query never asked for `activity_logs`, or the history in the file belongs to other boards — the report distinguishes the two | whichever the report says |
| **N רשומות רשומות על מערכת** (N rows recorded as "system") | people the log identifies only by a number, and the user list in the file does not cover them | see section 5 |
| **צבעי הקבוצות** (the group colours) | the board's groups arrive in the colours they had on monday — the query asks for `groups { id title color }`. A report saying *צבעי ברירת מחדל* means the file was produced by an older query that did not ask for `color` | re-run request 1 and import again, or set the colours here by hand |
| **עמודות סטטוס** (the status colours) | each status arrives in the colour it had on monday. The vocabulary lives in the column's own definition, which the query asks for as `columns { id title type settings_str }`; where the file carries none, the cell's own `label_style` stands in. A report saying *צבעי ברירת מחדל* means neither was in the file | re-run request 1 and import again, or recolour the options from the column menu |
| **columns not imported / imported as another type** | every column with its reason | a business decision, not a failure |
| **formula columns** | the computed value is imported as text, and the formula itself is kept on the column | it can be turned into a live formula from the column menu, one column at a time |
| **תתי־פריטים** → *N עמודות קיימות בתתי־הפריטים ולא בפריטי האב* | on monday a sub-item belongs to a board of its own, with its own columns. Those are created here as the sub-items' columns alone — they show on the sub-item rows and never on the item | nothing; look for them on a sub-item row, not on the item. A column the parent board has too is one shared column, matched by title |

---

## 5. Known limits — these are not import bugs

**History is a window, not the life of the board.** monday keeps `activity_logs` for a period that
depends on the plan. The report says which date the log starts at; that is a fact about monday, not
about the migration.

**Imported log rows offer no undo.** The change happened in monday, possibly a year ago, and reverting
it would write a value from the past onto the item as it stands today.

**The user list is the account as it is now; the log is the board as it was.** In the real migration the
log was written by 21 people and 15 of them were not on the list — 4,672 rows heading for "מערכת". The
import also reads names from the board's own people columns, which brought 10 of them back. What is
left:

- A **negative** id (`-4`) is monday itself — its automations. "System" is the truth about those.
- A positive id with no name is a **person** the file cannot name: someone no longer in the account who
  also does not sit in any people cell on the board. The report counts them separately and says how many.

**Files are signed for one hour.** The links monday returns in `assets { public_url }` expire after an
hour, and the time is written inside the link itself. An export that sits on disk for a day arrives with
the file names and without the bytes — so export and import in one go, within the same hour. The report
says how many files came as links and how many had expired.

A signature cannot be extended, but the asset can be asked for again — and that does not need the board
exported a second time. [scripts/refresh_monday_links.py](../scripts/refresh_monday_links.py) reads the
asset ids the file already carries, fetches a freshly signed link for each, and writes a copy with the
links replaced and nothing else touched:

```bash
export MONDAY_TOKEN=...
python scripts/refresh_monday_links.py merged.json -o merged-fresh.json
python scripts/refresh_monday_links.py merged.json --check   # what's in the file, no token, no calls
```

An asset deleted in monday since the export has no new link; those are counted and keep their name.

**Five formula columns per request.** A board with more gets an error or empty strings back — export it
twice, each run naming a different set of column `ids`.

**Events with no equivalent here.** Some monday event types (column settings changed, subscribe /
unsubscribe, moves between boards) do not become log rows in this system. The report counts them by type
rather than dropping them silently.

---

## 6. Symptom → cause

| What you see | What happened |
|---|---|
| `הקובץ אינו תשובת API של מאנדיי: the file holds more than one board` | two different responses that each brought items — two boards in one file. One import builds one board |
| the board came up with no history, and the report talks about other boards | the history request ran without `boardId` (section 2) |
| the board came up, and the report says the query never asked for history | the query that ran is an older revision, without `activity_logs` |
| every log row is recorded as "מערכת" | the query did not ask for `users { id name email }` |
| formula / mirror / connect columns are empty on every item | the query did not ask for `display_value` — those three types do not answer in `text` at all |
| everything imported, but there are fewer items than in monday | `cursor` was not `null` and pages were left behind. The report says so explicitly |
| everything imported, but a change you made to the code is not there | the server is running from before the change — restart it, and Cmd+Shift+R in the tab |

---

## 7. Files

| File | What it is |
|---|---|
| [backend/monday_export.graphql](../backend/monday_export.graphql) | the three queries, with why each field is in them |
| [backend/monday_export.postman_collection.json](../backend/monday_export.postman_collection.json) | the same queries as ready-made requests, with the `boardId` checks |
| [scripts/merge_monday_export.py](../scripts/merge_monday_export.py) | the merge, with the checks of section 2 built in |
| [scripts/refresh_monday_links.py](../scripts/refresh_monday_links.py) | re-signs the attachment links when the export has gone stale |
| [backend/import_monday.py](../backend/import_monday.py) | the reader: what becomes what, and what goes into the report |
| [tests/test_import_query.py](../tests/test_import_query.py) | keeps the collection and the query from drifting apart |
