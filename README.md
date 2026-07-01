# Generator rankingów zawodników (WZPN)

Narzędzie generuje sformatowane rankingi zawodników (.xlsx) na podstawie
średniego `score` z bazy. Obsługuje rankingi ogólne, z limitem „max N z klubu"
oraz progres między dwoma okresami. Osobno dla zawodników z pola i bramkarzy.

## Instalacja (jednorazowo)

```bash
pip install -r requirements.txt
cp .env.example .env        # potem uzupełnij .env swoimi danymi
```

Hasło do bazy trzymasz w `.env` (nie w kodzie, nie w repo).

## Połączenie z bazą

Jeśli łączysz się przez SSH, najpierw zestaw tunel w osobnym oknie:

```bash
ssh -L 5433:localhost:5432 uzytkownik@serwer
```

i ustaw w `.env`: `DB_HOST=localhost`, `DB_PORT=5433`.

## Codzienne użycie

Wszystko, co zmieniasz na co dzień, jest w **`config.py`**:

- `RANK_BY` — `"league"` (kategoria, np. „3 liga") albo `"play"` (grupa, np. „3 liga grupa 1")
- `LEAGUE_IDS` / `PLAY_IDS` / `REGION_IDS` — co bierzemy (UUID)
- `TOP_N` — ile pozycji (10, 30…)
- `MAX_PER_CLUB` — limit z klubu (`None` = bez limitu)
- `CLUB_LEVEL` — limit po `"club"` (prawdziwy klub) albo `"team"` (drużyna)
- `MIN_MECZE` — próg kwalifikacji (niski dla rankingu miesięcznego, wyższy dla sezonu)
- `PLAYER_GROUP` — `"outfield"` / `"keeper"` / `"both"`
- `PROGRES_OKRES_A` / `PROGRES_OKRES_B` — daty dwóch okresów do progresu

Potem:

```bash
python generuj_rankingi.py
```

Plik trafia do `data/ranking_<rank_by>_<data>.xlsx`.

## Nadpisywanie z linii poleceń (bez ruszania configu)

```bash
python generuj_rankingi.py --top-n 30 --min-mecze 3 --rank-by play
python generuj_rankingi.py --player-group outfield --no-progres
python generuj_rankingi.py --max-per-club 0          # 0 = bez limitu klubowego
python generuj_rankingi.py --help                    # pełna lista
```

## Arkusze w wynikowym pliku

Zależnie od ustawień, dla każdej grupy (polowi / bramkarze):

- **Ogólny** — top N całej kategorii/grupy, bez limitu klubowego
- **Max N z klubu** — top N z limitem zawodników na klub
- **Progres** — porównanie średniej z okresu A i B + różnica

TOP 3 każdej grupy jest podświetlone, nazwisko pogrubione.

## Pliki

```
config.py              # ustawienia — to dotykasz na co dzień
generuj_rankingi.py    # główny skrypt (nie trzeba edytować)
queries/ranking.sql    # zapytanie rankingu — czytelne, edytowalne
queries/progres.sql    # zapytanie progresu
.env                   # dane połączenia (NIE w repo)
data/                  # tu lądują wygenerowane .xlsx
```

## Uwaga o „max N z klubu"

Domyślnie (`CLUB_LEVEL="club"`) limit liczy się po **klubie** (`clubs._id`),
więc dwie drużyny tego samego klubu (np. „Alfa I" i „Alfa II") liczą się
wspólnie. Twój pierwotny skrypt SQL liczył po nazwie drużyny — jeśli chcesz to
stare zachowanie, ustaw `CLUB_LEVEL="team"`.
