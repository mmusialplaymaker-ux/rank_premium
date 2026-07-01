-- ════════════════════════════════════════════════════════════════════════════
-- ranking.sql
-- ════════════════════════════════════════════════════════════════════════════
-- Bazowy ranking zawodników po średnim score (× 100), w obrębie league.name
-- albo play.name. Obsługuje:
--   • limit max N z klubu (po clubs._id albo teams._id)
--   • osobno polowych / bramkarzy
--   • próg min. liczby meczów
--
-- Placeholdery {...} podstawia Python z config.py. Jeśli chcesz odpalić ręcznie
-- w pgAdmin, podmień je sam (opis każdego niżej).
--
-- {season_id}        UUID sezonu
-- {league_in}        lista UUID lig: 'a','b',...  (albo podzapytanie)
-- {rank_group_col}   c.name (dla league) albo d.name (dla play)
-- {join_plays}       pusty string LUB "JOIN plays d ON s.play_id = d._id"
-- {keeper_value}     false (polowi) albo true (bramkarze)
-- {min_mecze}        liczba, np. 5
-- {club_partition}   kolumna do PARTITION BY przy limicie klubowym
--                    (cl._id dla "club", b._id dla "team")
-- {max_per_club}     liczba (np. 2) — wstrzykiwane jako warunek lub 999999
-- {top_n}            liczba pozycji w finalnym rankingu
-- ════════════════════════════════════════════════════════════════════════════

WITH single_player_scores AS (
    SELECT
        x.player_id,
        x.league_id,
        x.play_id,
        MAX(x.team_id)        AS team_id,
        AVG(x.score)          AS raw_avg,
        COUNT(x.score)        AS mecze_count
    FROM pm_player_match_score x
    JOIN pm_player_match_stats m
        ON x.match_id  = m.match_id
       AND x.player_id = m.player_id
    WHERE x.season_id = '{season_id}'
      AND x.league_id IN ({league_in})
      {play_filter}
      AND m.is_keeper = {keeper_value}
      AND m.minutes > 0
      AND x.score IS NOT NULL
      AND x.score != 'NaN'::double precision
    GROUP BY x.player_id, x.league_id, x.play_id
    HAVING COUNT(x.score) > {min_mecze}
),
club_ranking AS (
    SELECT
        s.player_id,
        a.firstname,
        a.lastname,
        LEFT(a.date_of_birth, 4)::int            AS yob,
        b.name                                   AS team_name,
        cl.name                                  AS club_name,
        ROUND((s.raw_avg * 100)::numeric, 1)     AS avg_score,
        s.mecze_count                            AS mecze_count,
        c.name                                   AS league_name,
        {play_name_select}                       AS play_name,
        ROW_NUMBER() OVER (
            PARTITION BY {rank_group_col}, {club_partition}
            ORDER BY s.raw_avg DESC
        ) AS rank_in_club
    FROM single_player_scores s
        JOIN players a ON s.player_id = a._id
        JOIN teams   b ON s.team_id   = b._id
        LEFT JOIN clubs cl ON b.club_id = cl._id
        JOIN leagues c ON s.league_id = c._id
        {join_plays}
),
final_stats AS (
    SELECT
        player_id, firstname, lastname, yob, team_name, club_name,
        avg_score, mecze_count, league_name, play_name, rank_in_club,
        ROW_NUMBER() OVER (
            PARTITION BY {rank_group_col_final}
            ORDER BY avg_score DESC
        ) AS rank_position
    FROM club_ranking
    WHERE rank_in_club <= {max_per_club}
)
SELECT
    rank_position,
    firstname,
    lastname,
    yob,
    club_name,
    team_name,
    league_name,
    play_name,
    avg_score,
    mecze_count,
    player_id
FROM final_stats
WHERE rank_position <= {top_n}
ORDER BY {rank_group_col_final} ASC, avg_score DESC;
