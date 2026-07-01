-- ════════════════════════════════════════════════════════════════════════════
-- progres.sql
-- ════════════════════════════════════════════════════════════════════════════
-- Porównuje średni score zawodnika w dwóch okresach (A wcześniejszy,
-- B późniejszy) i liczy progres = avg_B - avg_A.
-- Bierze tylko zawodników, którzy w OBU okresach mają min. liczbę meczów.
--
-- Placeholdery:
--   {season_id}      UUID sezonu
--   {league_in}      lista UUID lig
--   {rank_group_col} c.name (league) albo d.name (play)
--   {join_plays}     pusty albo "JOIN plays d ON s.play_id = d._id"
--   {play_name_select} d.name albo 'Ranking Ogólny'
--   {keeper_value}   false / true
--   {a_start} {a_end}  granice okresu A (YYYY-MM-DD)
--   {b_start} {b_end}  granice okresu B
--   {progres_min}    min. mecze w każdym okresie
--   {club_partition} cl._id albo b._id
--   {max_per_club}   limit z klubu (lub 999999)
--   {top_n}          ile pozycji
-- ════════════════════════════════════════════════════════════════════════════

WITH period_scores AS (
    SELECT
        x.player_id,
        x.league_id,
        x.play_id,
        MAX(x.team_id) AS team_id,
        -- okres A
        AVG(CASE WHEN x.match_date::date BETWEEN '{a_start}' AND '{a_end}'
                 THEN x.score END)                                   AS avg_a,
        COUNT(CASE WHEN x.match_date::date BETWEEN '{a_start}' AND '{a_end}'
                   THEN x.score END)                                 AS mecze_a,
        -- okres B
        AVG(CASE WHEN x.match_date::date BETWEEN '{b_start}' AND '{b_end}'
                 THEN x.score END)                                   AS avg_b,
        COUNT(CASE WHEN x.match_date::date BETWEEN '{b_start}' AND '{b_end}'
                   THEN x.score END)                                 AS mecze_b
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
),
filtered AS (
    SELECT *
    FROM period_scores
    WHERE mecze_a >= {progres_min}
      AND mecze_b >= {progres_min}
),
club_ranking AS (
    SELECT
        s.player_id,
        a.firstname,
        a.lastname,
        LEFT(a.date_of_birth, 4)::int                         AS yob,
        b.name                                                AS team_name,
        cl.name                                               AS club_name,
        ROUND((s.avg_a * 100)::numeric, 1)                    AS avg_a,
        ROUND((s.avg_b * 100)::numeric, 1)                    AS avg_b,
        ROUND(((s.avg_b - s.avg_a) * 100)::numeric, 1)        AS progres,
        s.mecze_a,
        s.mecze_b,
        c.name                                                AS league_name,
        {play_name_select}                                    AS play_name,
        ROW_NUMBER() OVER (
            PARTITION BY {rank_group_col}, {club_partition}
            ORDER BY (s.avg_b - s.avg_a) DESC
        ) AS rank_in_club
    FROM filtered s
        JOIN players a ON s.player_id = a._id
        JOIN teams   b ON s.team_id   = b._id
        LEFT JOIN clubs cl ON b.club_id = cl._id
        JOIN leagues c ON s.league_id = c._id
        {join_plays}
),
final_stats AS (
    SELECT
        player_id, firstname, lastname, yob, team_name, club_name,
        avg_a, avg_b, progres, mecze_a, mecze_b,
        league_name, play_name, rank_in_club,
        ROW_NUMBER() OVER (
            PARTITION BY {rank_group_col_final}
            ORDER BY progres DESC
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
    avg_a,
    avg_b,
    progres,
    mecze_a,
    mecze_b,
    player_id
FROM final_stats
WHERE rank_position <= {top_n}
ORDER BY {rank_group_col_final} ASC, progres DESC;
